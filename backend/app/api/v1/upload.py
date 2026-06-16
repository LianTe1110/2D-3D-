"""LeiaPix AI - 图片上传 API

POST /api/v1/upload
- Magic Bytes 校验实际文件格式
- EXIF 自动旋转纠偏
- 超过 8192px 等比缩放
- 长边 256px 缩略图
- 原图 + 缩略图写入 MinIO
- 写入 PostgreSQL images 表
"""

import io
import uuid
import logging

from fastapi import APIRouter, Depends, File, UploadFile, HTTPException
from PIL import Image, ImageOps
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.models.image import Image as ImageModel
from app.models.user import User
from app.services.storage_service import get_minio_client
from app.api.deps import RateLimiter

logger = logging.getLogger(__name__)
router = APIRouter()

# 默认用户 ID (开发阶段使用，后续接入 JWT 后替换)
DEFAULT_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")

# Magic Bytes 签名表
MAGIC_SIGNATURES: dict[bytes, str] = {
    b"\xff\xd8\xff": "jpg",       # JPEG
    b"\x89PNG\r\n\x1a\n": "png",  # PNG
    b"RIFF": "webp",              # WebP (RIFF 容器)
    b"BM": "bmp",                 # BMP
}

# 允许的格式
ALLOWED_FORMATS = {"jpg", "png", "webp", "bmp"}

# 基准分辨率上限
MAX_RESOLUTION = 8192

# 缩略图长边
THUMBNAIL_LONG_SIDE = 256


def _detect_format_by_magic_bytes(data: bytes) -> str | None:
    """通过 Magic Bytes 检测文件实际格式"""
    for signature, fmt in MAGIC_SIGNATURES.items():
        if data.startswith(signature):
            # WebP 需要二次确认: RIFF....WEBP
            if signature == b"RIFF":
                if len(data) >= 12 and data[8:12] == b"WEBP":
                    return "webp"
                continue
            return fmt
    return None


def _fix_exif_rotation(image: Image.Image) -> Image.Image:
    """根据 EXIF 信息自动旋转图片纠偏"""
    try:
        return ImageOps.exif_transpose(image)
    except Exception:
        return image


def _scale_to_max_resolution(image: Image.Image, max_px: int) -> tuple[Image.Image, bool]:
    """等比缩放图片，使长边不超过 max_px。返回 (图片, 是否缩放过)"""
    w, h = image.size
    if w <= max_px and h <= max_px:
        return image, False

    # 计算缩放比例
    ratio = min(max_px / w, max_px / h)
    new_w = round(w * ratio)
    new_h = round(h * ratio)
    # 使用 LANCZOS 高质量缩放
    resized = image.resize((new_w, new_h), Image.LANCZOS)
    return resized, True


def _generate_thumbnail(image: Image.Image, long_side: int) -> tuple[Image.Image, int, int]:
    """生成缩略图，长边为 long_side，等比缩放。返回 (缩略图, 宽, 高)"""
    w, h = image.size
    if w >= h:
        ratio = long_side / w
    else:
        ratio = long_side / h
    new_w = round(w * ratio)
    new_h = round(h * ratio)
    thumb = image.resize((new_w, new_h), Image.LANCZOS)
    return thumb, new_w, new_h


async def _ensure_default_user(session: AsyncSession) -> None:
    """确保默认用户存在（开发阶段使用）"""
    from sqlalchemy import select
    result = await session.execute(select(User).where(User.id == DEFAULT_USER_ID))
    if result.scalar_one_or_none() is None:
        from app.core.security import hash_password
        default_user = User(
            id=DEFAULT_USER_ID,
            username="default",
            email="default@leiapix.local",
            password_hash=hash_password("default"),
            plan="free",
        )
        session.add(default_user)
        await session.flush()


@router.post("/upload", summary="上传图片", dependencies=[Depends(RateLimiter("upload"))])
async def upload_image(file: UploadFile = File(...)):
    """上传图片到 MinIO 存储，返回 image_id 和元信息"""
    settings = get_settings()

    # ---- 1. 读取文件数据 ----
    content = await file.read()

    # ---- 2. 校验文件大小 (≤ 20MB) ----
    max_size = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    if len(content) > max_size:
        logger.warning(f"Upload rejected: file too large ({len(content)} bytes)")
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": "FILE_TOO_LARGE",
                "message": f"File size exceeds {settings.MAX_UPLOAD_SIZE_MB}MB limit",
            },
        )

    # ---- 3. Magic Bytes 校验实际格式 ----
    detected_fmt = _detect_format_by_magic_bytes(content)
    if detected_fmt is None or detected_fmt not in ALLOWED_FORMATS:
        logger.warning(f"Upload rejected: invalid magic bytes, detected={detected_fmt}")
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": "INVALID_FORMAT",
                "message": f"Unsupported image format. Supported: JPG, PNG, WEBP, BMP",
            },
        )

    # ---- 4. PIL 解析 + EXIF 旋转纠偏 ----
    try:
        image = Image.open(io.BytesIO(content))
        image.load()  # 立即加载，确保数据完整
    except Exception:
        raise HTTPException(
            status_code=400,
            detail={"error_code": "INVALID_IMAGE", "message": "Cannot parse image file"},
        )

    # EXIF 自动旋转纠偏
    image = _fix_exif_rotation(image)

    # 确保为 RGB 模式 (处理 RGBA/P/L 等模式)
    if image.mode not in ("RGB", "L"):
        image = image.convert("RGB")

    width, height = image.size
    logger.info(f"Upload: filename={file.filename}, format={detected_fmt}, size={width}x{height}, bytes={len(content)}")

    # ---- 5. 最小分辨率校验 ----
    if width < 256 or height < 256:
        raise HTTPException(
            status_code=400,
            detail={"error_code": "RESOLUTION_TOO_LOW", "message": "Minimum resolution is 256x256"},
        )

    # ---- 6. 等比缩放至基准分辨率 (长边 ≤ 8192px) ----
    image, was_scaled = _scale_to_max_resolution(image, MAX_RESOLUTION)
    if was_scaled:
        width, height = image.size
        logger.info(f"Image scaled to {width}x{height}")

    # ---- 7. 编码原图为对应格式 ----
    ext = detected_fmt
    pil_save_format = {
        "jpg": "JPEG",
        "png": "PNG",
        "webp": "WEBP",
        "bmp": "BMP",
    }[ext]

    original_buffer = io.BytesIO()
    save_kwargs = {"format": pil_save_format}
    if pil_save_format == "JPEG":
        save_kwargs["quality"] = 95
    elif pil_save_format == "WEBP":
        save_kwargs["quality"] = 95
    image.save(original_buffer, **save_kwargs)
    original_buffer.seek(0)
    original_bytes = original_buffer.getbuffer().nbytes

    # ---- 8. 生成缩略图 (长边 256px) ----
    thumb_image, thumb_w, thumb_h = _generate_thumbnail(image, THUMBNAIL_LONG_SIDE)
    thumb_buffer = io.BytesIO()
    thumb_image.save(thumb_buffer, format="JPEG", quality=85)
    thumb_buffer.seek(0)
    thumb_bytes = thumb_buffer.getbuffer().nbytes

    # ---- 9. 上传到 MinIO ----
    image_id = uuid.uuid4()
    client = get_minio_client()

    storage_key = f"images/original/{DEFAULT_USER_ID}/{image_id}.{ext}"
    content_type_map = {"jpg": "image/jpeg", "png": "image/png", "webp": "image/webp", "bmp": "image/bmp"}
    client.put_object(
        bucket_name=settings.MINIO_BUCKET,
        object_name=storage_key,
        data=original_buffer,
        length=original_bytes,
        content_type=content_type_map[ext],
    )

    thumb_key = f"images/thumbnails/{DEFAULT_USER_ID}/{image_id}.jpg"
    client.put_object(
        bucket_name=settings.MINIO_BUCKET,
        object_name=thumb_key,
        data=thumb_buffer,
        length=thumb_bytes,
        content_type="image/jpeg",
    )

    original_url = f"/api/v1/files/{storage_key}"
    thumbnail_url = f"/api/v1/files/{thumb_key}"

    # ---- 10. 写入 PostgreSQL images 表 ----
    engine = create_async_engine(settings.DATABASE_URL)
    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        await _ensure_default_user(session)
        image_record = ImageModel(
            id=image_id,
            user_id=DEFAULT_USER_ID,
            filename=file.filename or f"upload.{ext}",
            original_url=original_url,
            thumbnail_url=thumbnail_url,
            width=width,
            height=height,
            format=ext,
            size_bytes=original_bytes,
            storage_key=storage_key,
            status="uploaded",
        )
        session.add(image_record)
        await session.commit()
    await engine.dispose()

    logger.info(f"Image uploaded: {image_id}, {width}x{height}, {original_bytes} bytes, format={ext}")

    return {
        "image_id": str(image_id),
        "user_id": str(DEFAULT_USER_ID),
        "filename": file.filename,
        "width": width,
        "height": height,
        "format": ext,
        "size_bytes": original_bytes,
        "original_url": original_url,
        "thumbnail_url": thumbnail_url,
        "storage_key": storage_key,
        "status": "uploaded",
    }


@router.get("/files/{storage_path:path}", summary="代理访问 MinIO 文件")
async def proxy_file(storage_path: str):
    """代理访问 MinIO 存储文件，避免前端直接访问 MinIO 导致 CORS 问题

    路径格式: /api/v1/files/images/original/{user_id}/{image_id}.png
    """
    from fastapi.responses import Response

    client = get_minio_client()
    settings = get_settings()

    try:
        response = client.get_object(
            bucket_name=settings.MINIO_BUCKET,
            object_name=storage_path,
        )
        data = response.read()
        content_type = response.headers.get("Content-Type", "application/octet-stream")
        response.close()
        response.release_conn()

        return Response(
            content=data,
            media_type=content_type,
            headers={
                "Cache-Control": "public, max-age=86400",
            },
        )
    except Exception:
        raise HTTPException(status_code=404, detail="File not found")
