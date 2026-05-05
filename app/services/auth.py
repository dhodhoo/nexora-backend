from __future__ import annotations

from datetime import timedelta
from typing import Any
import uuid

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import RevokedToken, User, UserRole, UserStatus
from app.utils.time import utc_now

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
bearer_scheme = HTTPBearer(auto_error=False)


class AuthService:
    @staticmethod
    def hash_password(password: str) -> str:
        return pwd_context.hash(password)

    @staticmethod
    def verify_password(password: str, password_hash: str) -> bool:
        return pwd_context.verify(password, password_hash)

    @staticmethod
    def _encode(payload: dict[str, Any]) -> str:
        return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)

    @staticmethod
    def decode(token: str) -> dict[str, Any]:
        try:
            return jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
        except jwt.InvalidTokenError as exc:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from exc

    @staticmethod
    def create_token(user: User, token_type: str) -> str:
        now = utc_now()
        if token_type == "refresh":
            exp = now + timedelta(minutes=settings.refresh_token_expire_minutes)
        else:
            exp = now + timedelta(minutes=settings.access_token_expire_minutes)
        payload = {
            "jti": str(uuid.uuid4()),
            "sub": user.user_id,
            "role": user.role.value,
            "community_id": user.community_id,
            "building_id": user.building_id,
            "status": user.status.value,
            "type": token_type,
            "iat": int(now.timestamp()),
            "exp": int(exp.timestamp()),
        }
        return AuthService._encode(payload)


def _token_from_credentials(credentials: HTTPAuthorizationCredentials | None) -> str:
    if not credentials or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    return credentials.credentials


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    if not settings.auth_enabled:
        user = db.execute(select(User).where(User.role == UserRole.ADMIN)).scalar_one_or_none()
        if user:
            request.state.current_user = user
            return user
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Auth disabled but admin not found")

    token = _token_from_credentials(credentials)
    payload = AuthService.decode(token)
    jti = payload.get("jti")
    token_type = payload.get("type")
    if token_type != "access":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Access token required")

    revoked = db.execute(select(RevokedToken).where(RevokedToken.jti == jti)).scalar_one_or_none()
    if revoked:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token revoked")

    user = db.execute(select(User).where(User.user_id == payload.get("sub"))).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    if user.status != UserStatus.ACTIVE:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is not active")

    request.state.current_user = user
    return user


def require_roles(*roles: UserRole):
    def dependency(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
        return user

    return dependency


def ensure_community_access(community_id: str, user: User) -> None:
    if user.role == UserRole.ADMIN:
        return
    if user.community_id != community_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Community scope mismatch")


def ensure_building_access(building_id: str, user: User) -> None:
    if user.role == UserRole.ADMIN:
        return
    if user.building_id != building_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Building scope mismatch")
