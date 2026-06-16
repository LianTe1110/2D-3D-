"""LeiaPix AI - 视频导出异步任务

路线 B (后端方案, 推荐, 质量更高):
  利用 Playwright (headless Chromium) 静默打开前端 3D 渲染页面,
  自动播放动画并逐帧截取 Canvas 画面, 最终调用系统 ffmpeg 命令行
  压制成标准 1080p/30fps MP4 或 GIF, 存入 MinIO exports/ 目录。

7 步生命周期:
  0%  初始化
  10% 准备渲染页面 (Playwright 启动浏览器)
  20% 加载场景数据
  40% 逐帧截取 Canvas (核心耗时)
  70% ffmpeg 编码视频/GIF
  90% 上传至 MinIO
  95% 更新数据库记录
  100% 完成

导出格式:
  - mp4:  H.264 编码, 分辨率 720p/1080p/4k, 帧率 24/30/60fps
  - gif:  调色板优化, 宽度 320/480/640px, 帧率 10/15/24fps
  - depth_png: 直接从 MinIO 下载深度图, 无需录制
"""

import asyncio
import logging
import os
import shutil
import subprocess
import tempfile
import uuid
from datetime import datetime
from pathlib import Path

from app.core.celery_app import celery_app
from app.core.config import get_settings

logger = logging.getLogger(__name__)

# ============ 分辨率映射 ============
RESOLUTION_MAP = {
    "720p": (1280, 720),
    "1080p": (1920, 1080),
    "4k": (3840, 2160),
}

GIF_SIZE_MAP = {
    "320": 320,
    "480": 480,
    "640": 640,
}


# ============ 进度推送工具 ============

async def _update_progress(task_id: str, user_id: str, progress: float, step: str, message: str):
    """更新任务进度到 Redis + Pub/Sub"""
    from app.core.redis import redis_client
    await redis_client.set_task_progress(
        task_id=task_id,
        status="processing" if progress < 100 else "completed",
        progress=progress,
        task_type="export",
        user_id=user_id,
        result={"export_id": task_id, "step": step} if progress < 100 else None,
    )


def _sync_update_progress(task_id: str, user_id: str, progress: float, step: str, message: str):
    """同步版本的进度更新 (Celery 任务内调用)"""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.create_task(_update_progress(task_id, user_id, progress, step, message))
        else:
            loop.run_until_complete(_update_progress(task_id, user_id, progress, step, message))
    except RuntimeError:
        loop = asyncio.new_event_loop()
        loop.run_until_complete(_update_progress(task_id, user_id, progress, step, message))


# ============ Playwright 帧捕获 ============

async def _capture_frames_with_playwright(
    scene_id: str,
    image_id: str,
    depth_map_id: str,
    render_params: dict,
    animation_params: dict,
    animation: dict,
    resolution: tuple[int, int],
    fps: int,
    duration_seconds: int,
    frames_dir: str,
    task_id: str,
    user_id: str,
) -> int:
    """使用 Playwright 打开前端 3D 页面, 逐帧截取 Canvas

    Returns:
        实际捕获的帧数
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        raise RuntimeError("playwright 未安装, 请运行: pip install playwright && playwright install chromium")

    settings = get_settings()
    # 前端页面 URL (需要前端提供带参数的渲染页面)
    frontend_url = f"http://localhost:5173/export?scene_id={scene_id}&image_id={image_id}&depth_map_id={depth_map_id}"

    total_frames = fps * duration_seconds
    frame_interval_ms = 1000 / fps

    async with async_playwright() as p:
        # 启动 headless 浏览器
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                f"--window-size={resolution[0]},{resolution[1]}",
            ],
        )

        context = await browser.new_context(
            viewport={"width": resolution[0], "height": resolution[1]},
            device_scale_factor=1,
        )

        page = await context.new_page()

        # 导出页面注入脚本: 自动播放动画并暴露 Canvas 引用
        await page.add_init_script("""
            // 暴露 Canvas 截图接口
            window.__exportCapture = function() {
                const canvas = document.querySelector('canvas');
                if (!canvas) return null;
                return canvas.toDataURL('image/png');
            };
        """)

        logger.info(f"[Export] Navigating to {frontend_url}")
        await page.goto(frontend_url, wait_until="networkidle", timeout=30000)

        # 等待 3D 场景加载完成
        await page.wait_for_selector("canvas", timeout=15000)
        await page.wait_for_timeout(2000)  # 额外等待纹理加载

        # 注入动画参数并启动播放
        anim_type = animation.get("type", "swing")
        amplitude = animation.get("amplitude", 0.5)
        speed = animation.get("speed", 1.0)

        await page.evaluate(f"""
            if (window.__setAnimationParams) {{
                window.__setAnimationParams({{
                    type: '{anim_type}',
                    amplitude: {amplitude},
                    speed: {speed},
                    isPlaying: true,
                }});
            }}
        """)

        await page.wait_for_timeout(500)  # 等待动画启动

        # 逐帧截取
        captured = 0
        for i in range(total_frames):
            # 截取 Canvas
            canvas_data = await page.evaluate("window.__exportCapture()")
            if canvas_data:
                # 解码 base64 并保存为 PNG
                import base64
                data = canvas_data.split(",")[1]
                frame_path = os.path.join(frames_dir, f"frame_{i:06d}.png")
                with open(frame_path, "wb") as f:
                    f.write(base64.b64decode(data))
                captured += 1

            # 更新进度 (40% ~ 70% 区间)
            frame_progress = 40 + (i / total_frames) * 30
            _sync_update_progress(
                task_id, user_id, frame_progress,
                "capturing", f"帧捕获 {i+1}/{total_frames}"
            )

            # 等待下一帧时间
            await page.wait_for_timeout(int(frame_interval_ms))

        await browser.close()

    logger.info(f"[Export] Captured {captured}/{total_frames} frames")
    return captured


# ============ ffmpeg 编码 ============

def _encode_mp4(frames_dir: str, output_path: str, fps: int, resolution: tuple[int, int]) -> str:
    """使用 ffmpeg 将帧序列编码为 H.264 MP4

    Args:
        frames_dir: 帧图片目录
        output_path: 输出 MP4 路径
        fps: 帧率
        resolution: (width, height)

    Returns:
        输出文件路径
    """
    input_pattern = os.path.join(frames_dir, "frame_%06d.png")

    cmd = [
        "ffmpeg", "-y",
        "-framerate", str(fps),
        "-i", input_pattern,
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "18",
        "-pix_fmt", "yuv420p",
        "-vf", f"scale={resolution[0]}:{resolution[1]}:force_original_aspect_ratio=decrease,pad={resolution[0]}:{resolution[1]}:(ow-iw)/2:(oh-ih)/2",
        "-movflags", "+faststart",
        output_path,
    ]

    logger.info(f"[Export] Encoding MP4: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

    if result.returncode != 0:
        logger.error(f"[Export] ffmpeg MP4 encoding failed: {result.stderr}")
        raise RuntimeError(f"ffmpeg encoding failed: {result.stderr}")

    return output_path


def _encode_gif(frames_dir: str, output_path: str, fps: int, width: int) -> str:
    """使用 ffmpeg 将帧序列编码为优化调色板 GIF

    两步法: 先生成调色板, 再用调色板编码 GIF

    Args:
        frames_dir: 帧图片目录
        output_path: 输出 GIF 路径
        fps: 帧率
        width: GIF 宽度

    Returns:
        输出文件路径
    """
    input_pattern = os.path.join(frames_dir, "frame_%06d.png")
    palette_path = os.path.join(frames_dir, "palette.png")

    # Step 1: 生成调色板
    palette_cmd = [
        "ffmpeg", "-y",
        "-framerate", str(fps),
        "-i", input_pattern,
        "-vf", f"scale={width}:-1:flags=lanczos,palettegen=max_colors=256:stats_mode=full",
        palette_path,
    ]

    logger.info(f"[Export] Generating GIF palette: {' '.join(palette_cmd)}")
    result = subprocess.run(palette_cmd, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        logger.error(f"[Export] Palette generation failed: {result.stderr}")
        raise RuntimeError(f"Palette generation failed: {result.stderr}")

    # Step 2: 用调色板编码 GIF
    gif_cmd = [
        "ffmpeg", "-y",
        "-framerate", str(fps),
        "-i", input_pattern,
        "-i", palette_path,
        "-lavfi", f"scale={width}:-1:flags=lanczos[x];[x][1:v]paletteuse=dither=bayer:bayer_scale=5",
        output_path,
    ]

    logger.info(f"[Export] Encoding GIF: {' '.join(gif_cmd)}")
    result = subprocess.run(gif_cmd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        logger.error(f"[Export] GIF encoding failed: {result.stderr}")
        raise RuntimeError(f"GIF encoding failed: {result.stderr}")

    return output_path


# ============ depth_png 导出 (无需录制) ============

async def _export_depth_png(
    export_id: str,
    task_id: str,
    user_id: str,
    depth_map_id: str,
    image_id: str,
) -> dict:
    """导出深度图 PNG — 直接从 MinIO 下载深度图并复制到 exports/ 目录

    Returns:
        {"storage_key": ..., "file_size_bytes": ...}
    """
    from app.services.storage_service import download_image, upload_export_file, get_export_url

    # 下载深度图
    depth_storage_key = f"depth_maps/{user_id}/{image_id}.png"
    depth_image = download_image(depth_storage_key)

    # 转为 PNG 字节流
    import io
    buffer = io.BytesIO()
    depth_image.save(buffer, format="PNG")
    buffer.seek(0)
    file_bytes = buffer.getvalue()

    # 上传到 exports/ 目录
    storage_key = f"exports/{user_id}/{export_id}_depth.png"
    upload_export_file(storage_key, file_bytes, content_type="image/png")

    download_url = get_export_url(storage_key)

    return {
        "storage_key": storage_key,
        "download_url": download_url,
        "file_size_bytes": len(file_bytes),
    }


# ============ 主任务 ============

@celery_app.task(
    bind=True,
    name="app.tasks.export_task.export_video",
    max_retries=2,
    time_limit=300,
    soft_time_limit=270,
    queue="export",
)
def export_video(
    self,
    export_id: str,
    task_id: str,
    scene_id: str,
    user_id: str,
    export_format: str = "mp4",
    resolution: str = "1080p",
    fps: int = 30,
    duration_seconds: int = 5,
    animation: dict | None = None,
    image_id: str = "",
    depth_map_id: str = "",
    render_params: dict | None = None,
    animation_params: dict | None = None,
):
    """异步视频/GIF/深度图导出任务 — 7 步生命周期

    Args:
        export_id: 导出记录 ID
        task_id: 任务记录 ID
        scene_id: 场景 ID
        user_id: 用户 ID
        export_format: 导出格式 (mp4/gif/depth_png)
        resolution: 分辨率 (720p/1080p/4k)
        fps: 帧率
        duration_seconds: 时长(秒)
        animation: 动画参数
        image_id: 图片 ID
        depth_map_id: 深度图 ID
        render_params: 渲染参数
        animation_params: 动画参数(场景保存的)
    """
    animation = animation or {}
    render_params = render_params or {}
    animation_params = animation_params or {}

    logger.info(f"[Export] Starting export: export_id={export_id}, format={export_format}, resolution={resolution}")

    # ---- 0% 初始化 ----
    _sync_update_progress(task_id, user_id, 0, "init", "初始化导出任务")

    # ---- 更新 tasks 表 started_at ----
    try:
        from sqlalchemy import create_engine
        from sqlalchemy.orm import Session
        from app.models.task import Task as TaskModel
        from app.models.export import Export as ExportModel

        settings = get_settings()
        sync_engine = create_engine(settings.DATABASE_URL_SYNC)

        with Session(sync_engine) as session:
            task = session.get(TaskModel, uuid.UUID(task_id))
            if task:
                task.status = "processing"
                task.started_at = datetime.utcnow()
                session.commit()
    except Exception as e:
        logger.warning(f"[Export] Failed to update task started_at: {e}")

    try:
        # ============ depth_png 快捷路径 ============
        if export_format == "depth_png":
            _sync_update_progress(task_id, user_id, 10, "preparing", "准备深度图导出")

            loop = asyncio.new_event_loop()
            result = loop.run_until_complete(
                _export_depth_png(export_id, task_id, user_id, depth_map_id, image_id)
            )
            loop.close()

            # 更新数据库
            _update_export_record(export_id, result["storage_key"], result["download_url"], result["file_size_bytes"])
            _update_task_completed(task_id, export_id, result["download_url"], result["file_size_bytes"])

            _sync_update_progress(task_id, user_id, 100, "completed", "深度图导出完成")
            logger.info(f"[Export] depth_png export completed: {export_id}")
            return {"status": "completed", "export_id": export_id}

        # ============ MP4 / GIF 录制路径 ============

        # ---- 10% 准备渲染页面 ----
        _sync_update_progress(task_id, user_id, 10, "preparing", "准备渲染环境")

        res = RESOLUTION_MAP.get(resolution, (1920, 1080))

        # 创建临时帧目录
        temp_dir = tempfile.mkdtemp(prefix="leiapix_export_")
        frames_dir = os.path.join(temp_dir, "frames")
        os.makedirs(frames_dir, exist_ok=True)

        logger.info(f"[Export] Temp directory: {temp_dir}")

        # ---- 20% 加载场景数据 ----
        _sync_update_progress(task_id, user_id, 20, "loading_scene", "加载场景数据")

        # ---- 40% 逐帧截取 Canvas ----
        _sync_update_progress(task_id, user_id, 40, "capturing", "开始帧捕获")

        loop = asyncio.new_event_loop()
        captured_frames = loop.run_until_complete(
            _capture_frames_with_playwright(
                scene_id=scene_id,
                image_id=image_id,
                depth_map_id=depth_map_id,
                render_params=render_params,
                animation_params=animation_params,
                animation=animation,
                resolution=res,
                fps=fps,
                duration_seconds=duration_seconds,
                frames_dir=frames_dir,
                task_id=task_id,
                user_id=user_id,
            )
        )
        loop.close()

        if captured_frames == 0:
            raise RuntimeError("No frames captured from Playwright")

        # ---- 70% ffmpeg 编码 ----
        _sync_update_progress(task_id, user_id, 70, "encoding", "编码视频")

        output_filename = f"{export_id}.{export_format}"
        output_path = os.path.join(temp_dir, output_filename)

        if export_format == "mp4":
            _encode_mp4(frames_dir, output_path, fps, res)
        elif export_format == "gif":
            gif_width = GIF_SIZE_MAP.get("480", 480)
            _encode_gif(frames_dir, output_path, fps, gif_width)

        # ---- 90% 上传至 MinIO ----
        _sync_update_progress(task_id, user_id, 90, "uploading", "上传至存储")

        with open(output_path, "rb") as f:
            file_bytes = f.read()

        file_size = len(file_bytes)
        ext = "mp4" if export_format == "mp4" else "gif"
        storage_key = f"exports/{user_id}/{export_id}.{ext}"

        loop = asyncio.new_event_loop()
        loop.run_until_complete(_upload_export_to_minio(storage_key, file_bytes, export_format))
        loop.close()

        from app.services.storage_service import get_export_url
        download_url = get_export_url(storage_key)

        # ---- 95% 更新数据库记录 ----
        _sync_update_progress(task_id, user_id, 95, "updating_db", "更新数据库记录")

        _update_export_record(export_id, storage_key, download_url, file_size)
        _update_task_completed(task_id, export_id, download_url, file_size)

        # ---- 100% 完成 ----
        _sync_update_progress(task_id, user_id, 100, "completed", "导出完成")

        logger.info(f"[Export] Export completed: {export_id}, size={file_size} bytes, url={download_url}")

        # 清理临时文件
        try:
            shutil.rmtree(temp_dir)
        except Exception:
            pass

        return {"status": "completed", "export_id": export_id, "download_url": download_url}

    except Exception as e:
        logger.error(f"[Export] Export failed: {e}", exc_info=True)

        # 更新任务状态为失败
        _update_task_failed(task_id, str(e))
        _update_export_failed(export_id)

        _sync_update_progress(task_id, user_id, 0, "failed", f"导出失败: {e}")

        # 重试
        raise self.retry(exc=e, countdown=5)


# ============ 数据库更新工具 ============

def _update_export_record(export_id: str, storage_key: str, download_url: str, file_size_bytes: int):
    """更新 exports 表记录"""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app.models.export import Export as ExportModel

    settings = get_settings()
    sync_engine = create_engine(settings.DATABASE_URL_SYNC)

    with Session(sync_engine) as session:
        export = session.get(ExportModel, uuid.UUID(export_id))
        if export:
            export.storage_key = storage_key
            export.download_url = download_url
            export.file_size_bytes = file_size_bytes
            export.status = "ready"
            session.commit()


def _update_task_completed(task_id: str, export_id: str, download_url: str, file_size_bytes: int):
    """更新 tasks 表为 completed"""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app.models.task import Task as TaskModel

    settings = get_settings()
    sync_engine = create_engine(settings.DATABASE_URL_SYNC)

    with Session(sync_engine) as session:
        task = session.get(TaskModel, uuid.UUID(task_id))
        if task:
            task.status = "completed"
            task.progress = 100
            task.completed_at = datetime.utcnow()
            task.result = {
                "export_id": export_id,
                "download_url": download_url,
                "file_size_bytes": file_size_bytes,
            }
            session.commit()


def _update_task_failed(task_id: str, error_message: str):
    """更新 tasks 表为 failed"""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app.models.task import Task as TaskModel

    settings = get_settings()
    sync_engine = create_engine(settings.DATABASE_URL_SYNC)

    with Session(sync_engine) as session:
        task = session.get(TaskModel, uuid.UUID(task_id))
        if task:
            task.status = "failed"
            task.error_message = error_message
            task.completed_at = datetime.utcnow()
            session.commit()


def _update_export_failed(export_id: str):
    """更新 exports 表为 failed"""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app.models.export import Export as ExportModel

    settings = get_settings()
    sync_engine = create_engine(settings.DATABASE_URL_SYNC)

    with Session(sync_engine) as session:
        export = session.get(ExportModel, uuid.UUID(export_id))
        if export:
            export.status = "failed"
            session.commit()


async def _upload_export_to_minio(storage_key: str, file_bytes: bytes, export_format: str):
    """上传导出文件到 MinIO"""
    from app.services.storage_service import upload_export_file
    content_type = {
        "mp4": "video/mp4",
        "gif": "image/gif",
        "depth_png": "image/png",
    }.get(export_format, "application/octet-stream")

    upload_export_file(storage_key, file_bytes, content_type=content_type)
