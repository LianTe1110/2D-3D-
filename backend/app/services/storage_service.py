"""LeiaPix AI - MinIO 对象存储服务"""

import io
import logging
from uuid import UUID

from minio import Minio
from PIL import Image

from app.core.config import get_settings

logger = logging.getLogger(__name__)


def get_minio_client() -> Minio:
    """获取 MinIO 客户端"""
    settings = get_settings()
    return Minio(
        endpoint=settings.MINIO_ENDPOINT,
        access_key=settings.MINIO_ACCESS_KEY,
        secret_key=settings.MINIO_SECRET_KEY,
        secure=settings.MINIO_SECURE,
    )


def download_image(storage_key: str) -> Image.Image:
    """从 MinIO 下载图片并返回 PIL Image

    Args:
        storage_key: MinIO 对象键, 如 "images/original/{user_id}/{image_id}.jpg"

    Returns:
        PIL Image 对象
    """
    settings = get_settings()
    client = get_minio_client()
    response = None
    try:
        response = client.get_object(settings.MINIO_BUCKET, storage_key)
        image_data = response.read()
        return Image.open(io.BytesIO(image_data))
    finally:
        if response:
            response.close()
            response.release_conn()


def upload_depth_map(
    user_id: str,
    image_id: str,
    depth_map_image: Image.Image,
) -> str:
    """上传深度图 PNG 到 MinIO

    Args:
        user_id: 用户 ID
        image_id: 图片 ID
        depth_map_image: 深度图 PIL Image (mode="L")

    Returns:
        MinIO 存储键
    """
    settings = get_settings()
    client = get_minio_client()

    storage_key = f"depth_maps/{user_id}/{image_id}.png"
    buffer = io.BytesIO()
    depth_map_image.save(buffer, format="PNG")
    buffer.seek(0)
    data_length = buffer.getbuffer().nbytes

    client.put_object(
        bucket_name=settings.MINIO_BUCKET,
        object_name=storage_key,
        data=buffer,
        length=data_length,
        content_type="image/png",
    )

    logger.info(f"Depth map uploaded: {storage_key} ({data_length} bytes)")
    return storage_key


def get_depth_map_url(storage_key: str) -> str:
    """获取深度图的访问 URL

    Args:
        storage_key: MinIO 对象键

    Returns:
        通过后端 API 代理的 URL (避免 CORS 问题)
    """
    return f"/api/v1/files/{storage_key}"


def upload_enhanced_image(
    user_id: str,
    image_id: str,
    enhanced_image: Image.Image,
    format: str = "PNG",
) -> str:
    """上传增强图到 MinIO

    Args:
        user_id: 用户 ID
        image_id: 图片 ID
        enhanced_image: 增强 PIL Image
        format: 保存格式 (PNG/JPEG)

    Returns:
        MinIO 存储键
    """
    settings = get_settings()
    client = get_minio_client()

    ext = "png" if format.upper() == "PNG" else "jpg"
    content_type = "image/png" if ext == "png" else "image/jpeg"
    storage_key = f"enhanced/{user_id}/{image_id}.{ext}"

    buffer = io.BytesIO()
    enhanced_image.save(buffer, format=format, quality=95 if ext == "jpg" else None)
    buffer.seek(0)
    data_length = buffer.getbuffer().nbytes

    client.put_object(
        bucket_name=settings.MINIO_BUCKET,
        object_name=storage_key,
        data=buffer,
        length=data_length,
        content_type=content_type,
    )

    logger.info(f"Enhanced image uploaded: {storage_key} ({data_length} bytes)")
    return storage_key


def get_enhanced_url(storage_key: str) -> str:
    """获取增强图的访问 URL"""
    return f"/api/v1/files/{storage_key}"


def upload_mpi_layer(
    user_id: str,
    image_id: str,
    layer_index: int,
    layer_image: Image.Image,
) -> str:
    """上传 MPI 层纹理 PNG 到 MinIO

    Args:
        user_id: 用户 ID
        image_id: 图片 ID
        layer_index: 层索引
        layer_image: RGBA 层纹理 PIL Image

    Returns:
        MinIO 存储键
    """
    settings = get_settings()
    client = get_minio_client()

    storage_key = f"mpi_layers/{user_id}/{image_id}/layer_{layer_index}.png"
    buffer = io.BytesIO()
    layer_image.save(buffer, format="PNG")
    buffer.seek(0)
    data_length = buffer.getbuffer().nbytes

    client.put_object(
        bucket_name=settings.MINIO_BUCKET,
        object_name=storage_key,
        data=buffer,
        length=data_length,
        content_type="image/png",
    )

    logger.info(f"MPI layer uploaded: {storage_key} ({data_length} bytes)")
    return storage_key


def get_mpi_layer_url(storage_key: str) -> str:
    """获取 MPI 层纹理的访问 URL"""
    return f"/api/v1/files/{storage_key}"


# ============ 导出文件 (MP4/GIF/PNG) ============

def upload_export_file(
    storage_key: str,
    file_bytes: bytes,
    content_type: str = "video/mp4",
) -> str:
    """上传导出文件 (MP4/GIF/PNG) 到 MinIO

    Args:
        storage_key: MinIO 对象键, 如 "exports/{user_id}/{export_id}.mp4"
        file_bytes: 文件二进制数据
        content_type: MIME 类型

    Returns:
        MinIO 存储键
    """
    settings = get_settings()
    client = get_minio_client()

    data_length = len(file_bytes)
    buffer = io.BytesIO(file_bytes)

    client.put_object(
        bucket_name=settings.MINIO_BUCKET,
        object_name=storage_key,
        data=buffer,
        length=data_length,
        content_type=content_type,
    )

    logger.info(f"Export file uploaded: {storage_key} ({data_length} bytes)")
    return storage_key


def get_export_url(storage_key: str) -> str:
    """获取导出文件的访问 URL"""
    return f"/api/v1/files/{storage_key}"


def download_export_file(storage_key: str) -> bytes:
    """从 MinIO 下载导出文件并返回二进制数据

    Args:
        storage_key: MinIO 对象键

    Returns:
        文件二进制数据
    """
    settings = get_settings()
    client = get_minio_client()
    response = None
    try:
        response = client.get_object(settings.MINIO_BUCKET, storage_key)
        return response.read()
    finally:
        if response:
            response.close()
            response.release_conn()
