"""Managed memory API."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from cptr.utils.config import AuthResult, check_access
from cptr.utils.memory import (
    remember,
    read_memory_state,
    save_memory_settings,
)

router = APIRouter(prefix="/api/memory", tags=["memory"])
COOKIE_NAME = "cptr_session"


def _get_auth(request: Request) -> AuthResult:
    token = request.cookies.get(COOKIE_NAME)
    client_host = request.client.host if request.client else "127.0.0.1"
    auth = check_access(client_host=client_host, jwt_token=token)
    if not auth or not auth.user_id:
        raise HTTPException(401, "authentication required")
    return auth


def _get_user(request: Request) -> str:
    return _get_auth(request).user_id or ""


def _require_admin(request: Request) -> AuthResult:
    auth = _get_auth(request)
    if auth.role != "admin":
        raise HTTPException(403, "admin required")
    return auth


class MemorySettingsRequest(BaseModel):
    settings: dict[str, Any]


class MemoryUpdateRequest(BaseModel):
    scope: Literal["user", "workspace"]
    operations: list[dict[str, Any]]
    workspace: str = ""


@router.get("")
async def get_memory(request: Request, workspace: str = Query("")):
    user_id = _get_user(request)
    return await read_memory_state(user_id, workspace)


@router.put("/config")
async def put_memory_settings(body: MemorySettingsRequest, request: Request):
    _require_admin(request)
    return {"settings": await save_memory_settings(body.settings)}


@router.post("/update")
async def update_memory(body: MemoryUpdateRequest, request: Request):
    user_id = _get_user(request)
    return await remember(
        user_id=user_id,
        workspace=body.workspace,
        scope=body.scope,
        operations=body.operations,
    )
