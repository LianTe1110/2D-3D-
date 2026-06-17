"""LeiaPix AI - 3D 场景渲染异步任务 (Phase 2)

对标 Immersity AI: 将 MPI 场景数据 + 相机轨迹渲染为 3D 场景。
"""

import asyncio
import logging
import sys
import uuid
from datetime import datetime
from pathlib import Path

from app.core.celery_app import celery_app
from app.core.redis import redis_client

logger = logging.getLogger(__name__)

# ai-models 目录加入 Python 路径
AI_MODELS_PATH = str(Path(__file__).resolve().parents[3] / "ai-models")
if AI_MODELS_PATH not in sys.path:
    sys.path.insert(0, AI_MODELS_PATH)


@celery_app.task(
    bind=True,
    name="app.tasks.render_task.render_3d",
    max_retries=2,
    time_limit=120,
    soft_time_limit=110,
)
def render_3d(self, scene_id: str, user_id: str, render_params: dict):
    """异步 3D 场景渲染任务

    从 image_id + depth_map_id 初始化场景, 生成 MPI 层数据,
    保存到 scenes 表, 返回 scene_data。

    Args:
        scene_id: 场景 ID (DB scenes 表)
        user_id: 用户 ID
        render_params: 渲染参数字典
            - image_id: 图片 ID
            - depth_map_id: 深度图 ID
            - fov: 相机视场角
            - parallax_scale: 视差缩放
            - layer_count: 层数
            - etc.
    """
    image_id = render_params.get("image_id", "")
    depth_map_id = render_params.get("depth_map_id", "")

    async def _run():
        # ========== 1. 初始化 ==========
        await redis_client.set_task_progress(
            task_id=scene_id, status="processing", progress=0,
            task_type="render", user_id=user_id,
        )

        try:
            # ========== 2. 下载原图 + 深度图 ==========
            await redis_client.set_task_progress(
                task_id=scene_id, status="processing", progress=10,
                task_type="render", user_id=user_id,
            )
            from app.services.storage_service import download_image

            image = download_image(f"images/original/{user_id}/{image_id}.jpg")
            logger.info(f"Downloaded original image: {image_id}")

            # ========== 3. 加载模型并生成 MPI 层 ==========
            await redis_client.set_task_progress(
                task_id=scene_id, status="processing", progress=30,
                task_type="render", user_id=user_id,
            )

            from model_manager import ModelManager
            manager = ModelManager()
            fused = await manager.run_full_pipeline(image)

            await redis_client.set_task_progress(
                task_id=scene_id, status="processing", progress=60,
                task_type="render", user_id=user_id,
            )

            engine = manager.get_engine("depth_anything_v2")
            n_layers = fused.get("num_detected_layers", 3)
            scene_layers = engine.decompose_scene(fused, image, n_layers=n_layers)

            # ========== 4. 上传 MPI 层纹理到 MinIO ==========
            await redis_client.set_task_progress(
                task_id=scene_id, status="processing", progress=75,
                task_type="render", user_id=user_id,
            )

            from app.services.storage_service import upload_mpi_layer, get_mpi_layer_url

            mpi_layers = []
            for i, layer_data in enumerate(scene_layers):
                storage_key = upload_mpi_layer(user_id, image_id, i, layer_data["texture"])
                layer_url = get_mpi_layer_url(storage_key)
                mpi_layers.append({
                    "id": f"layer_{i}",
                    "textureUrl": layer_url,
                    "zIndex": layer_data["z_position"],
                    "motionScale": layer_data["motion_scale"],
                    "parallaxDirection": "both",
                    "blendMode": "premultiplied",
                })

            # ========== 5. 更新 scenes 表 ==========
            await redis_client.set_task_progress(
                task_id=scene_id, status="processing", progress=90,
                task_type="render", user_id=user_id,
            )

            from app.core.config import get_settings
            from sqlalchemy import create_engine
            from sqlalchemy.orm import Session
            from app.models.scene import Scene

            settings = get_settings()
            sync_engine = create_engine(settings.DATABASE_URL_SYNC)

            with Session(sync_engine) as session:
                scene = session.get(Scene, uuid.UUID(scene_id))
                if scene:
                    scene.status = "ready"
                    scene.layer_count = n_layers
                    scene.layers = {"mpi_layers": mpi_layers}
                    scene.models_used = {"depth": "dav2", "seg": "sam2"}
                    scene.camera_config = {
                        "fov": render_params.get("fov", 60),
                        "parallax_scale": render_params.get("parallax_scale", 0.3),
                        "near_plane": render_params.get("near_plane", 0.1),
                        "far_plane": render_params.get("far_plane", 100),
                        "base_distance": render_params.get("camera_distance", 5),
                    }
                    scene.metadata = {
                        "width": image.width,
                        "height": image.height,
                        "layerCount": n_layers,
                        "modelUsed": "depth_anything_v2",
                    }
                    session.commit()

            # ========== 6. 完成 ==========
            result_data = {
                "scene_id": scene_id,
                "status": "ready",
                "scene_data_url": f"/api/v1/files/scenes/{user_id}/{scene_id}/scene.json",
                "render_params": {
                    "fov": render_params.get("fov", 60),
                    "parallax_scale": render_params.get("parallax_scale", 0.3),
                    "near_plane": render_params.get("near_plane", 0.1),
                    "far_plane": render_params.get("far_plane", 100),
                    "camera_distance": render_params.get("camera_distance", 5),
                    "mesh_subdivision": render_params.get("mesh_subdivision", 256),
                    "layer_count": n_layers,
                    "layer_scales": [0.3, 0.8, 1.5],
                    "edge_freeze_strength": 0.8,
                    "camera_parallax": True,
                },
                "animation_params": {
                    "type": "swing",
                    "amplitude": 0.3,
                    "speed": 1.0,
                    "duration": 3.0,
                    "direction": "horizontal",
                },
                "mpi_layers": mpi_layers,
            }

            await redis_client.set_task_progress(
                task_id=scene_id,
                status="completed",
                progress=100,
                task_type="render",
                user_id=user_id,
                result=result_data,
            )

            logger.info(f"Scene render completed: {scene_id}, {n_layers} layers")
            return result_data

        except Exception as e:
            logger.error(f"Scene render failed for {scene_id}: {e}")
            await redis_client.set_task_progress(
                task_id=scene_id,
                status="failed",
                progress=0,
                task_type="render",
                user_id=user_id,
                error_message=str(e),
            )
            raise self.retry(exc=e, countdown=30)

    # 在同步 Celery 任务中运行异步代码
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    redis_client._pool = None
    try:
        return loop.run_until_complete(_run())
    finally:
        loop.close()