"""LeiaPix AI - FastAPI 依赖注入

- get_current_user: JWT 认证，解析 Authorization Bearer token
- get_optional_user: 可选认证（未登录时返回默认用户）
- RateLimiter: 基于 Redis 计数器的请求限流器
"""

import logging
import uuid

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.redis import redis_client
from app.core.security import decode_token

logger = logging.getLogger(__name__)

# 默认用户 ID (开发阶段，未登录时使用)
DEFAULT_USER_ID = "00000000-0000-0000-0000-000000000001"

# Bearer Token 提取器
bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> dict:
    """JWT 认证依赖：解析 Bearer token，返回用户信息

    Returns:
        {"user_id": str, "plan": str}
    """
    if credentials is None:
        raise HTTPException(
            status_code=401,
            detail={"error_code": "NOT_AUTHENTICATED", "message": "Missing Authorization header"},
        )

    payload = decode_token(credentials.credentials)
    if payload is None:
        raise HTTPException(
            status_code=401,
            detail={"error_code": "INVALID_TOKEN", "message": "Invalid or expired token"},
        )

    if payload.get("type") != "access":
        raise HTTPException(
            status_code=401,
            detail={"error_code": "INVALID_TOKEN_TYPE", "message": "Expected access token, got refresh token"},
        )

    user_id = payload.get("sub")
    if user_id is None:
        raise HTTPException(
            status_code=401,
            detail={"error_code": "MALFORMED_TOKEN", "message": "Token missing subject"},
        )

    return {"user_id": user_id, "plan": payload.get("plan", "free")}


async def get_optional_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> dict:
    """可选认证：有 token 则解析，无 token 则返回默认用户（开发阶段）"""
    if credentials is None:
        return {"user_id": DEFAULT_USER_ID, "plan": "free"}

    payload = decode_token(credentials.credentials)
    if payload is None or payload.get("type") != "access":
        return {"user_id": DEFAULT_USER_ID, "plan": "free"}

    user_id = payload.get("sub", DEFAULT_USER_ID)
    return {"user_id": user_id, "plan": payload.get("plan", "free")}


# ---- 限流器 ----

# 不同套餐的限流配置: {plan: {endpoint: (max_requests, window_seconds)}}
RATE_LIMITS = {
    "free": {
        "upload": (100, 3600),          # 免费用户: 100次/小时
        "depth_estimate": (100, 3600),   # 100次/小时
        "render": (100, 3600),           # 100次/小时
        "enhance": (50, 3600),           # 50次/小时
        "export": (50, 3600),            # 50次/小时
    },
    "pro": {
        "upload": (1000, 3600),          # Pro: 1000次/小时
        "depth_estimate": (1000, 3600),
        "render": (1000, 3600),
        "enhance": (500, 3600),
        "export": (500, 3600),
    },
}


class RateLimiter:
    """基于 Redis 计数器的请求限流器

    用法:
        # 在路由中作为依赖注入
        @router.post("/upload", dependencies=[Depends(RateLimiter("upload"))])
        async def upload(...): ...

        # 或在需要 user_id 的路由中组合使用
        @router.post("/upload")
        async def upload(user=Depends(get_optional_user), _=Depends(RateLimiter("upload"))):
    """

    def __init__(self, endpoint: str):
        self.endpoint = endpoint

    async def __call__(self, request: Request) -> None:
        # 尝试从请求状态获取 user_id（由 get_optional_user 设置）
        # 回退到 IP 地址
        user = getattr(request.state, "user", None)
        if user:
            identifier = user["user_id"]
            plan = user.get("plan", "free")
        else:
            # 尝试从 Authorization header 解析
            auth_header = request.headers.get("authorization", "")
            if auth_header.startswith("Bearer "):
                payload = decode_token(auth_header[7:])
                if payload and payload.get("type") == "access":
                    identifier = payload["sub"]
                    plan = payload.get("plan", "free")
                else:
                    identifier = f"ip:{request.client.host if request.client else 'unknown'}"
                    plan = "free"
            else:
                identifier = f"ip:{request.client.host if request.client else 'unknown'}"
                plan = "free"

        # 获取该套餐的限流配置
        plan_limits = RATE_LIMITS.get(plan, RATE_LIMITS["free"])
        max_requests, window_seconds = plan_limits.get(
            self.endpoint, RATE_LIMITS["free"][self.endpoint]
        )

        # 检查限流
        allowed, remaining = await redis_client.check_rate_limit(
            user_id=identifier,
            endpoint=self.endpoint,
            max_requests=max_requests,
            window_seconds=window_seconds,
        )

        if not allowed:
            logger.warning(f"Rate limited: {identifier} on {self.endpoint}")
            raise HTTPException(
                status_code=429,
                detail={
                    "error_code": "RATE_LIMITED",
                    "message": f"Rate limit exceeded for '{self.endpoint}': {max_requests} requests per {window_seconds // 60} minutes",
                    "retry_after_seconds": window_seconds,
                },
            )
