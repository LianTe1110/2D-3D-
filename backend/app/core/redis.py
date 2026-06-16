"""LeiaPix AI - Redis 缓存工具类

封装任务进度 (Hash) 和 API 限流计数器 (String) 的读写操作。
"""

import json
from typing import Any

import redis.asyncio as aioredis

from app.core.config import get_settings


class RedisClient:
    """Redis 异步客户端封装"""

    def __init__(self) -> None:
        self._pool: aioredis.Redis | None = None

    async def _get_pool(self) -> aioredis.Redis:
        if self._pool is None:
            settings = get_settings()
            self._pool = aioredis.from_url(
                settings.REDIS_URL,
                decode_responses=True,
                max_connections=20,
            )
        return self._pool

    async def close(self) -> None:
        if self._pool:
            await self._pool.aclose()
            self._pool = None

    # --------------- 任务进度 (Hash) ---------------
    # Key: task:{task_id}
    # Fields: status, progress, type, error_message, result, user_id

    async def set_task_progress(
        self,
        task_id: str,
        status: str,
        progress: float,
        task_type: str | None = None,
        error_message: str | None = None,
        result: dict | None = None,
        user_id: str | None = None,
        ttl: int = 3600,
    ) -> None:
        """设置任务进度并发布到 Pub/Sub 频道"""
        r = await self._get_pool()
        key = f"task:{task_id}"
        data: dict[str, str] = {
            "status": status,
            "progress": str(progress),
            "task_id": task_id,
        }
        if task_type:
            data["type"] = task_type
        if error_message:
            data["error_message"] = error_message
        if result:
            data["result"] = json.dumps(result, ensure_ascii=False)
        if user_id:
            data["user_id"] = user_id

        await r.hset(key, mapping=data)  # type: ignore[arg-type]
        await r.expire(key, ttl)

        # 发布到 Pub/Sub 频道，供 WebSocket 实时推送
        if user_id:
            channel = f"task_progress:{user_id}"
            await r.publish(channel, json.dumps(data, ensure_ascii=False))

    async def get_task_progress(self, task_id: str) -> dict[str, Any] | None:
        """获取任务进度"""
        r = await self._get_pool()
        key = f"task:{task_id}"
        data = await r.hgetall(key)
        if not data:
            return None
        result: dict[str, Any] = dict(data)
        if "progress" in result:
            result["progress"] = float(result["progress"])
        if "result" in result:
            result["result"] = json.loads(result["result"])
        return result

    async def delete_task_progress(self, task_id: str) -> None:
        """删除任务进度缓存"""
        r = await self._get_pool()
        await r.delete(f"task:{task_id}")

    # --------------- API 限流 (String counter) ---------------
    # Key: rate_limit:{user_id}:{endpoint}
    # Value: 请求计数, TTL: 60s

    async def check_rate_limit(
        self,
        user_id: str,
        endpoint: str,
        max_requests: int = 30,
        window_seconds: int = 60,
    ) -> tuple[bool, int]:
        """检查 API 请求频率限制

        Returns:
            (allowed, remaining) — 是否允许, 剩余次数
        """
        r = await self._get_pool()
        key = f"rate_limit:{user_id}:{endpoint}"
        current = await r.get(key)

        if current is None:
            await r.set(key, 1, ex=window_seconds)
            return True, max_requests - 1

        count = int(current)
        if count >= max_requests:
            return False, 0

        await r.incr(key)
        return True, max_requests - count - 1

    # --------------- 通用缓存 ---------------

    async def set_cache(self, key: str, value: Any, ttl: int = 3600) -> None:
        """设置缓存"""
        r = await self._get_pool()
        await r.set(key, json.dumps(value, ensure_ascii=False), ex=ttl)

    async def get_cache(self, key: str) -> Any | None:
        """获取缓存"""
        r = await self._get_pool()
        data = await r.get(key)
        if data is None:
            return None
        return json.loads(data)

    async def delete_cache(self, key: str) -> None:
        """删除缓存"""
        r = await self._get_pool()
        await r.delete(key)


# 全局单例
redis_client = RedisClient()
