"""LeiaPix AI - WebSocket 实时状态流

路由: /api/v1/ws?user_id={user_id}

工作原理:
    1. 客户端通过 WebSocket 连接，携带 user_id 参数
    2. 服务端订阅 Redis 频道 "task_progress:{user_id}"
    3. Celery 任务在执行时，按步长将进度写入 Redis Hash 并发布到该频道
    4. WebSocket 服务收到 Pub/Sub 消息后，实时推送给客户端

消息格式 (服务端 → 客户端):
    {
        "type": "task_progress" | "task_completed" | "task_failed" | "scene_update",
        "data": {
            "task_id": "...",
            "progress": 0.65,
            "step": "depth_estimation",
            "message": "正在生成深度图..."
        }
    }
"""

import asyncio
import json
import logging
from enum import Enum

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from app.core.redis import redis_client

logger = logging.getLogger(__name__)

router = APIRouter()


class WSMessageType(str, Enum):
    """WebSocket 消息类型枚举"""

    TASK_PROGRESS = "task_progress"
    TASK_COMPLETED = "task_completed"
    TASK_FAILED = "task_failed"
    SCENE_UPDATE = "scene_update"


# 进度步长映射: progress 值 → 步骤描述
PROGRESS_STEPS = {
    0: ("initialized", "任务初始化"),
    10: ("downloading", "正在下载原图"),
    30: ("loading_model", "正在加载模型"),
    50: ("inference", "正在推理"),
    80: ("uploading", "正在上传结果"),
    90: ("saving", "正在保存数据"),
    100: ("completed", "处理完成"),
}


def _resolve_step(progress: float) -> tuple[str, str]:
    """根据进度值解析当前步骤 key 和中文描述"""
    matched_key = "initialized"
    matched_msg = "处理中"
    for threshold, (key, msg) in PROGRESS_STEPS.items():
        if progress >= threshold:
            matched_key = key
            matched_msg = msg
    return matched_key, matched_msg


def _build_message(task_data: dict) -> dict:
    """将 Redis Hash 中的任务数据构建为 WebSocket 推送消息"""
    status = task_data.get("status", "unknown")
    progress = float(task_data.get("progress", 0))
    task_id = task_data.get("task_id", "")
    task_type = task_data.get("type", "")

    # 根据状态确定消息类型
    if status == "completed":
        msg_type = WSMessageType.TASK_COMPLETED
    elif status == "failed":
        msg_type = WSMessageType.TASK_FAILED
    else:
        msg_type = WSMessageType.TASK_PROGRESS

    step_key, step_msg = _resolve_step(progress)

    message = {
        "type": msg_type,
        "data": {
            "task_id": task_id,
            "progress": round(progress / 100, 2),  # 转为 0~1
            "step": step_key,
            "message": step_msg,
            "task_type": task_type,
        },
    }

    # completed 时附带 result（Redis 中存储的是 JSON 字符串，需解析回对象）
    if status == "completed" and "result" in task_data:
        try:
            message["data"]["result"] = json.loads(task_data["result"])
        except (json.JSONDecodeError, TypeError):
            message["data"]["result"] = task_data["result"]

    # failed 时附带 error_message
    if status == "failed" and "error_message" in task_data:
        message["data"]["error_message"] = task_data["error_message"]

    return message


@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    user_id: str = Query(..., description="用户 ID，用于订阅该用户的任务进度"),
):
    """WebSocket 实时状态推送端点

    连接后自动订阅该用户的任务进度频道，
    当 Celery 任务更新进度时，实时推送 task_progress 消息。
    """
    await websocket.accept()
    logger.info(f"WebSocket connected: user_id={user_id}")

    # 获取 Redis 连接池
    r = await redis_client._get_pool()

    # 创建独立的 Pub/Sub 连接
    pubsub = r.pubsub()
    channel = f"task_progress:{user_id}"
    await pubsub.subscribe(channel)

    try:
        # 两个并发任务: 监听 Pub/Sub + 监听客户端消息
        async def listen_pubsub():
            """监听 Redis Pub/Sub 消息并推送给客户端"""
            while True:
                message = await pubsub.get_message(
                    ignore_subscribe_messages=True, timeout=1.0
                )
                if message and message["type"] == "message":
                    try:
                        payload = json.loads(message["data"])
                        ws_message = _build_message(payload)
                        await websocket.send_json(ws_message)
                    except (json.JSONDecodeError, KeyError) as e:
                        logger.warning(f"Invalid pubsub message: {e}")
                await asyncio.sleep(0.1)

        async def listen_client():
            """监听客户端消息 (心跳 / 断开检测)"""
            while True:
                try:
                    data = await websocket.receive_text()
                    # 客户端心跳 ping
                    if data.strip() == "ping":
                        await websocket.send_json({"type": "pong"})
                except WebSocketDisconnect:
                    break

        # 并发运行两个监听器
        await asyncio.gather(
            listen_pubsub(),
            listen_client(),
            return_exceptions=True,
        )

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected: user_id={user_id}")
    except Exception as e:
        logger.error(f"WebSocket error for user_id={user_id}: {e}")
    finally:
        await pubsub.unsubscribe(channel)
        await pubsub.aclose()
        logger.info(f"WebSocket cleaned up: user_id={user_id}")
