"""LeiaPix AI - 认证 API

POST /api/v1/auth/register  — 用户注册
POST /api/v1/auth/login     — 用户登录（返回 access + refresh 双 Token）
POST /api/v1/auth/refresh   — 刷新令牌
GET  /api/v1/auth/me        — 获取当前用户信息
"""

import logging
import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.models.user import User

logger = logging.getLogger(__name__)
router = APIRouter()


# ---- 请求/响应模型 ----

class RegisterRequest(BaseModel):
    username: str
    email: EmailStr
    password: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int  # 秒


class UserResponse(BaseModel):
    id: str
    username: str
    email: str
    plan: str
    avatar_url: str | None
    created_at: str | None


# ---- API 端点 ----

@router.post("/auth/register", summary="用户注册", response_model=TokenResponse)
async def register(req: RegisterRequest):
    """注册新用户，自动签发双 Token"""
    settings = get_settings()
    engine = create_async_engine(settings.DATABASE_URL)
    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        # 检查邮箱是否已注册
        result = await session.execute(select(User).where(User.email == req.email))
        if result.scalar_one_or_none() is not None:
            raise HTTPException(
                status_code=409,
                detail={"error_code": "EMAIL_EXISTS", "message": "Email already registered"},
            )

        # 检查用户名是否已占用
        result = await session.execute(select(User).where(User.username == req.username))
        if result.scalar_one_or_none() is not None:
            raise HTTPException(
                status_code=409,
                detail={"error_code": "USERNAME_EXISTS", "message": "Username already taken"},
            )

        # 创建用户
        user = User(
            username=req.username,
            email=req.email,
            password_hash=hash_password(req.password),
            plan="free",
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        user_id = str(user.id)

    await engine.dispose()

    # 签发双 Token
    access_token = create_access_token(subject=user_id)
    refresh_token = create_refresh_token(subject=user_id)

    logger.info(f"User registered: {user_id} ({req.email})")

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.post("/auth/login", summary="用户登录", response_model=TokenResponse)
async def login(req: LoginRequest):
    """邮箱 + 密码登录，签发双 Token"""
    settings = get_settings()
    engine = create_async_engine(settings.DATABASE_URL)
    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        result = await session.execute(select(User).where(User.email == req.email))
        user = result.scalar_one_or_none()

    await engine.dispose()

    if user is None or not verify_password(req.password, user.password_hash):
        raise HTTPException(
            status_code=401,
            detail={"error_code": "INVALID_CREDENTIALS", "message": "Invalid email or password"},
        )

    # 更新最后登录时间
    engine = create_async_engine(settings.DATABASE_URL)
    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        db_user = await session.get(User, user.id)
        if db_user:
            db_user.last_login_at = datetime.utcnow()
            await session.commit()
    await engine.dispose()

    user_id = str(user.id)
    access_token = create_access_token(subject=user_id)
    refresh_token = create_refresh_token(subject=user_id)

    logger.info(f"User logged in: {user_id} ({req.email})")

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.post("/auth/refresh", summary="刷新令牌", response_model=TokenResponse)
async def refresh_token(req: RefreshRequest):
    """使用 refresh_token 换取新的 access_token + refresh_token"""
    payload = decode_token(req.refresh_token)

    if payload is None or payload.get("type") != "refresh":
        raise HTTPException(
            status_code=401,
            detail={"error_code": "INVALID_TOKEN", "message": "Invalid or expired refresh token"},
        )

    user_id = payload.get("sub")
    if user_id is None:
        raise HTTPException(
            status_code=401,
            detail={"error_code": "INVALID_TOKEN", "message": "Malformed token"},
        )

    # 验证用户仍然存在
    settings = get_settings()
    engine = create_async_engine(settings.DATABASE_URL)
    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        user = await session.get(User, uuid.UUID(user_id))
        if user is None:
            raise HTTPException(
                status_code=401,
                detail={"error_code": "USER_NOT_FOUND", "message": "User no longer exists"},
            )

    await engine.dispose()

    # 签发新的双 Token
    access_token = create_access_token(subject=user_id)
    new_refresh_token = create_refresh_token(subject=user_id)

    logger.info(f"Token refreshed for user: {user_id}")

    return TokenResponse(
        access_token=access_token,
        refresh_token=new_refresh_token,
        expires_in=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.get("/auth/me", summary="获取当前用户信息", response_model=UserResponse)
async def get_current_user_info(user_id: str = None):
    """获取当前登录用户信息（需要 Authorization header）"""
    if user_id is None:
        raise HTTPException(status_code=401, detail="Not authenticated")

    settings = get_settings()
    engine = create_async_engine(settings.DATABASE_URL)
    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        user = await session.get(User, uuid.UUID(user_id))
        if user is None:
            raise HTTPException(status_code=404, detail="User not found")

        result = UserResponse(
            id=str(user.id),
            username=user.username,
            email=user.email,
            plan=user.plan,
            avatar_url=user.avatar_url,
            created_at=user.created_at.isoformat() if user.created_at else None,
        )

    await engine.dispose()
    return result
