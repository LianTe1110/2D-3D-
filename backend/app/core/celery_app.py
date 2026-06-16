"""LeiaPix AI - Celery 应用配置

包含任务路由策略、GPU 资源并发控制与显存保护。
"""

from celery import Celery

from app.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "leiapix",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
)

# ============ 任务路由策略 ============
# 严格划分独立队列，防止 GPU 任务互相抢占显存
# 每个 Worker 容器仅消费自己对应的队列
celery_app.conf.task_routes = {
    "app.tasks.depth_task.estimate_depth": {"queue": "gpu_depth"},
    "app.tasks.render_task.render_3d": {"queue": "gpu_render"},
    "app.tasks.enhance_task.enhance_image": {"queue": "gpu_enhance"},
    "app.tasks.export_task.export_video": {"queue": "export"},
}

# ============ GPU 并发控制 ============
# 每个队列的 Worker 并发数，防止单张 GPU 显存溢出 (OOM)
#
# 关键约束:
#   - 24G 显存 (如 RTX 3090/4090): gpu_depth=2, gpu_enhance=1
#   - 12G 显存 (如 RTX 3060/4070): gpu_depth=1, gpu_enhance=1
#   - 8G  显存 (如 RTX 3060Ti):    gpu_depth=1, gpu_enhance=0 (禁用)
#
# Real-ESRGAN x4plus 在 1080p 图片上峰值显存约 4-6G
# Depth Anything V2 在 1080p 图片上峰值显存约 3-4G
# 两者绝不能在同一 GPU 上同时运行!
CELERY_WORKER_CONCURRENCY = {
    "gpu_depth": 2,      # 深度估计: 2 并发 (24G) / 1 并发 (12G)
    "gpu_render": 2,     # 3D 渲染: 2 并发
    "gpu_enhance": 1,    # 图像增强: 1 并发 (严格限制, 显存占用大)
    "export": 4,         # 视频导出: 4 并发 (CPU 密集, 无 GPU)
}

# ============ GPU 显存保护 ============
# 每个 Worker 容器通过环境变量 GPU_MAX_MEMORY_MB 配置显存上限
# 推理前检查当前显存占用, 超过阈值则拒绝任务 (防 OOM)
GPU_MAX_MEMORY_MB = {
    "gpu_depth": 8192,    # 深度估计: 最大 8G 显存
    "gpu_enhance": 10240, # 图像增强: 最大 10G 显存
}

# ============ 任务超时 ============
CELERY_TASK_TIME_LIMIT = {
    "depth": 60,         # 深度估计: 60s
    "render": 30,        # 3D 渲染: 30s
    "enhance": 120,      # 图像增强: 120s
    "export": 300,       # 视频导出: 300s
}

# ============ 通用配置 ============
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Shanghai",
    enable_utc=True,
    task_track_started=True,
    # 关键: acks_late=True + prefetch_multiplier=1
    # 确保任务只有在真正完成后才从队列移除
    # 防止 Worker OOM 崩溃后任务丢失
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    # 全局超时 (单任务可覆盖)
    task_time_limit=300,
    task_soft_time_limit=270,
    # 任务拒绝策略: Worker 内存不足时拒绝新任务
    task_reject_on_worker_lost=True,
)

# 自动发现任务模块
celery_app.autodiscover_tasks(["app.tasks"])


# ============ GPU 显存检查工具 ============

def check_gpu_memory(max_memory_mb: int) -> bool:
    """检查 GPU 显存是否充足

    Args:
        max_memory_mb: 最大允许显存占用 (MB)

    Returns:
        True 表示显存充足, 可以执行任务
    """
    if not settings.GPU_ENABLED:
        return True

    try:
        import torch
        if not torch.cuda.is_available():
            return True

        # 获取当前显存占用
        allocated = torch.cuda.memory_allocated() / (1024 * 1024)  # MB
        reserved = torch.cuda.memory_reserved() / (1024 * 1024)    # MB
        total = torch.cuda.get_device_properties(0).total_mem / (1024 * 1024)  # MB

        available = total - reserved

        if available < max_memory_mb * 0.3:
            # 剩余显存不足 30%, 拒绝任务
            return False

        return True

    except (ImportError, RuntimeError):
        # PyTorch 未安装或 CUDA 不可用, 允许任务 (CPU 模式)
        return True


def get_gpu_memory_info() -> dict:
    """获取 GPU 显存信息 (用于日志和监控)"""
    if not settings.GPU_ENABLED:
        return {"status": "disabled"}

    try:
        import torch
        if not torch.cuda.is_available():
            return {"status": "no_cuda"}

        allocated = torch.cuda.memory_allocated(0) / (1024 * 1024)
        reserved = torch.cuda.memory_reserved(0) / (1024 * 1024)
        total = torch.cuda.get_device_properties(0).total_mem / (1024 * 1024)

        return {
            "status": "ok",
            "device": torch.cuda.get_device_name(0),
            "total_mb": round(total, 1),
            "allocated_mb": round(allocated, 1),
            "reserved_mb": round(reserved, 1),
            "available_mb": round(total - reserved, 1),
            "utilization_pct": round(reserved / total * 100, 1),
        }

    except (ImportError, RuntimeError) as e:
        return {"status": "error", "message": str(e)}
