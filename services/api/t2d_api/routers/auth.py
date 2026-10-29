"""Auth endpoints: login, me."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..deps import CurrentUser, DbDep
from ..auth.passwords import verify_password
from ..auth.tokens import issue_token
from t2d_db.models import User

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    token: str
    user: dict


@router.post("/login", response_model=LoginResponse)
def login(body: LoginRequest, db: DbDep):
    user = db.query(User).filter_by(username=body.username.strip().lower()).first()
    if user is None or not verify_password(body.password, user.password_hash):
        # Uniform error: never reveal whether the username exists.
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="账号已停用")
    return LoginResponse(token=issue_token(user.id), user=user.as_dict())


@router.get("/me")
def me(user: CurrentUser):
    return user.as_dict()
