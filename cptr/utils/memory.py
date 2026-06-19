"""File-backed managed memory for cptr."""

from __future__ import annotations

import asyncio
import os
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cptr.env import DATA_DIR
from cptr.models import Config
from cptr.utils.workspace import ensure_cptr_gitignored

MEMORY_DIR_NAME = "memory"

DEFAULT_MEMORY_SETTINGS: dict[str, Any] = {
    "enabled": True,
    "tool_enabled": True,
    "background_review_enabled": True,
    "review_interval_turns": 10,
    "user_char_limit": 2000,
    "workspace_char_limit": 3000,
}

_memory_file_locks: dict[str, asyncio.Lock] = {}
_reviewed_messages: set[str] = set()


@dataclass(frozen=True)
class MemoryFile:
    path: Path
    character_limit: int


def _safe_id(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip(".-")
    return cleaned or "user"


def normalize_workspace_path(workspace: str) -> str:
    if not workspace:
        raise ValueError("workspace is required for workspace memory")
    return str(Path(workspace).expanduser().resolve())


def _user_memory_root(user_id: str) -> Path:
    return DATA_DIR / MEMORY_DIR_NAME / "users" / _safe_id(user_id)


def user_memory_path(user_id: str) -> Path:
    return _user_memory_root(user_id) / "USER.md"


def workspace_memory_path(user_id: str, workspace: str) -> Path:
    root = Path(normalize_workspace_path(workspace))
    return root / ".cptr" / MEMORY_DIR_NAME / "users" / _safe_id(user_id) / "WORKSPACE.md"


def _memory_file_lock(path: Path) -> asyncio.Lock:
    return _memory_file_locks.setdefault(str(path), asyncio.Lock())


def read_memory_entries(path: Path) -> list[str]:
    if not path.is_file():
        return []
    entries: list[str] = []
    for line in path.read_text(errors="replace").splitlines():
        line = line.strip()
        if not line.startswith("- "):
            continue
        entry = line[2:].strip()
        if entry:
            entries.append(entry)
    return entries


def format_memory_entries(entries: list[str]) -> str:
    rendered = "\n".join(f"- {normalize_memory_text(entry)}" for entry in entries if entry.strip())
    return f"{rendered}\n" if rendered else ""


def write_memory_entries(path: Path, entries: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    tmp.write_text(format_memory_entries(entries), encoding="utf-8")
    os.replace(tmp, path)


def measure_memory_entries(entries: list[str]) -> int:
    if not entries:
        return 0
    return len("\n".join(entries))


UNSAFE_MEMORY_CHARACTERS = ("\x00", "\u200b", "\u200c", "\u200d", "\ufeff")


def normalize_memory_text(content: str) -> str:
    return " ".join(str(content).split())


def memory_text_error(content: str) -> str | None:
    """Return a rejection reason for text that cannot be safely stored as memory."""
    if any(ch in content for ch in UNSAFE_MEMORY_CHARACTERS):
        return "memory content contains invisible or null characters"
    return None


async def get_memory_settings() -> dict[str, Any]:
    settings = {**DEFAULT_MEMORY_SETTINGS}
    for key in DEFAULT_MEMORY_SETTINGS:
        value = await Config.get(f"memory.{key}")
        if value is not None:
            settings[key] = value
    settings["review_interval_turns"] = max(1, int(settings.get("review_interval_turns") or 10))
    settings["user_char_limit"] = max(250, int(settings.get("user_char_limit") or 2000))
    settings["workspace_char_limit"] = max(250, int(settings.get("workspace_char_limit") or 3000))
    return settings


async def save_memory_settings(updates: dict[str, Any]) -> dict[str, Any]:
    await Config.upsert(
        {f"memory.{key}": value for key, value in updates.items() if key in DEFAULT_MEMORY_SETTINGS}
    )
    return await get_memory_settings()


async def resolve_memory_file(user_id: str, workspace: str, scope: str) -> MemoryFile:
    settings = await get_memory_settings()
    if scope == "user":
        return MemoryFile(
            path=user_memory_path(user_id),
            character_limit=int(settings["user_char_limit"]),
        )
    if scope == "workspace":
        return MemoryFile(
            path=workspace_memory_path(user_id, workspace),
            character_limit=int(settings["workspace_char_limit"]),
        )
    raise ValueError("scope must be 'user' or 'workspace'")


def apply_memory_batch(
    current_entries: list[str],
    operations: list[dict[str, Any]],
    character_limit: int,
) -> tuple[bool, str, list[str], str]:
    current_usage = f"{measure_memory_entries(current_entries)}/{character_limit}"
    if not operations:
        return False, "operations list is empty", current_entries, current_usage

    next_entries = list(current_entries)
    for index, operation in enumerate(operations):
        if not isinstance(operation, dict):
            return False, f"Operation {index + 1}: must be an object", current_entries, current_usage
        action = operation.get("action")
        content = normalize_memory_text(str(operation.get("content") or ""))
        old_text = normalize_memory_text(str(operation.get("old_text") or ""))
        operation_name = f"Operation {index + 1} ({action or 'unknown'})"

        if action in {"add", "replace"}:
            validation_error = memory_text_error(content)
            if validation_error:
                return False, f"{operation_name}: {validation_error}", current_entries, current_usage

        if action == "add":
            if not content:
                return False, f"{operation_name}: content is required", current_entries, current_usage
            if content not in next_entries:
                next_entries.append(content)
        elif action == "replace":
            if not old_text:
                return False, f"{operation_name}: old_text is required", current_entries, current_usage
            if not content:
                return False, f"{operation_name}: content is required", current_entries, current_usage
            matches = [i for i, entry in enumerate(next_entries) if old_text in entry]
            if not matches:
                return False, f"{operation_name}: no entry matched '{old_text}'", current_entries, current_usage
            if len({next_entries[i] for i in matches}) > 1:
                return (
                    False,
                    f"{operation_name}: old_text matched multiple distinct entries",
                    current_entries,
                    current_usage,
                )
            next_entries[matches[0]] = content
        elif action == "remove":
            if not old_text:
                return False, f"{operation_name}: old_text is required", current_entries, current_usage
            matches = [i for i, entry in enumerate(next_entries) if old_text in entry]
            if not matches:
                return False, f"{operation_name}: no entry matched '{old_text}'", current_entries, current_usage
            if len({next_entries[i] for i in matches}) > 1:
                return (
                    False,
                    f"{operation_name}: old_text matched multiple distinct entries",
                    current_entries,
                    current_usage,
                )
            next_entries.pop(matches[0])
        else:
            return (
                False,
                f"{operation_name}: unknown action; use add, replace, or remove",
                current_entries,
                current_usage,
            )

    next_usage_count = measure_memory_entries(next_entries)
    if next_usage_count > character_limit:
        return (
            False,
            f"final memory would be {next_usage_count}/{character_limit} chars; remove or shorten entries in the same batch",
            current_entries,
            current_usage,
        )
    return True, f"Applied {len(operations)} operation(s).", next_entries, f"{next_usage_count}/{character_limit}"


async def write_memory(
    user_id: str,
    workspace: str,
    scope: str,
    operations: list[dict[str, Any]],
) -> dict[str, Any]:
    memory_file = await resolve_memory_file(user_id, workspace, scope)
    if scope == "workspace":
        await asyncio.to_thread(ensure_cptr_gitignored, workspace)
    async with _memory_file_lock(memory_file.path):
        entries = await asyncio.to_thread(read_memory_entries, memory_file.path)
        success, message, next_entries, usage = apply_memory_batch(
            entries, operations, memory_file.character_limit
        )
        if not success:
            return {
                "success": False,
                "error": message,
                "entries": entries,
                "usage": usage,
                "scope": scope,
                "path": str(memory_file.path),
            }
        await asyncio.to_thread(write_memory_entries, memory_file.path, next_entries)
        return {
            "success": True,
            "message": message,
            "entries": next_entries,
            "usage": usage,
            "scope": scope,
            "path": str(memory_file.path),
        }


async def remember(
    user_id: str,
    workspace: str,
    scope: str,
    operations: list[dict[str, Any]],
) -> dict[str, Any]:
    settings = await get_memory_settings()
    if not settings["enabled"]:
        return {"success": False, "error": "memory writes are disabled"}
    return await write_memory(user_id, workspace, scope, operations)


async def read_memory_state(user_id: str, workspace: str) -> dict[str, Any]:
    settings = await get_memory_settings()
    user_memory = await resolve_memory_file(user_id, workspace, "user")
    user_entries = await asyncio.to_thread(read_memory_entries, user_memory.path)
    workspace_entries: list[str] = []
    workspace_usage = f"0/{settings['workspace_char_limit']}"
    workspace_path_value = ""
    if workspace:
        workspace_memory = await resolve_memory_file(user_id, workspace, "workspace")
        workspace_entries = await asyncio.to_thread(read_memory_entries, workspace_memory.path)
        workspace_usage = f"{measure_memory_entries(workspace_entries)}/{workspace_memory.character_limit}"
        workspace_path_value = str(workspace_memory.path)
    return {
        "settings": settings,
        "user": {
            "entries": user_entries,
            "usage": f"{measure_memory_entries(user_entries)}/{user_memory.character_limit}",
            "path": str(user_memory.path),
        },
        "workspace": {
            "entries": workspace_entries,
            "usage": workspace_usage,
            "path": workspace_path_value,
        },
    }


async def build_memory_prompt(user_id: str | None, workspace: str) -> str:
    if not user_id:
        return ""
    settings = await get_memory_settings()
    if not settings["enabled"]:
        return ""
    state = await read_memory_state(user_id, workspace)
    blocks: list[str] = []
    for key, title in (("user", "User Memory"), ("workspace", "Workspace Memory")):
        entries = state[key]["entries"]
        if not entries:
            continue
        blocks.append(
            f"[{title}] [{state[key]['usage']}]\n"
            + "\n".join(f"- {entry}" for entry in entries)
        )
    return "\n\n".join(blocks)


def summarize_recent_conversation(messages: list[dict[str, Any]], assistant_reply: str) -> str:
    recent_messages = messages[-16:]
    lines: list[str] = []
    for message in recent_messages:
        role = message.get("role", "unknown")
        content = message.get("content", "")
        if isinstance(content, list):
            content = " ".join(
                str(block.get("text", "")) for block in content if isinstance(block, dict)
            )
        text = str(content).strip()
        if len(text) > 1600:
            text = text[:1000] + "\n...(truncated)...\n" + text[-400:]
        if text:
            lines.append(f"{role}: {text}")
    if assistant_reply:
        text = assistant_reply.strip()
        if len(text) > 1600:
            text = text[:1000] + "\n...(truncated)...\n" + text[-400:]
        lines.append(f"assistant_final: {text}")
    return "\n\n".join(lines)


def build_memory_review_prompt(memory_state: dict[str, Any], workspace: str, transcript: str) -> str:
    return (
        "Review the completed conversation and decide whether cptr should remember "
        "stable facts. Return ONLY JSON with this shape:\n"
        '{"user": [{"action": "add|replace|remove", "content": "...", "old_text": "..."}], '
        '"workspace": [{"action": "add|replace|remove", "content": "...", "old_text": "..."}]}\n\n'
        "Use user memory only for durable user preferences, communication style, repeated "
        "corrections, or cross-workspace habits. Use workspace memory only for facts true "
        "in the current workspace, such as repo conventions, verification commands, "
        "architecture notes, or local tool quirks. If nothing is worth saving, return "
        '{"user": [], "workspace": []}.\n\n'
        f"Workspace: {workspace}\n\n"
        f"Current user memory ({memory_state['user']['usage']}):\n"
        + "\n".join(f"- {entry}" for entry in memory_state["user"]["entries"])
        + f"\n\nCurrent workspace memory ({memory_state['workspace']['usage']}):\n"
        + "\n".join(f"- {entry}" for entry in memory_state["workspace"]["entries"])
        + f"\n\nConversation:\n{transcript}"
    )


async def review_memory_after_turn(
    *,
    user_id: str,
    message_id: str,
    workspace: str,
    conversation_messages: list[dict[str, Any]],
    assistant_reply: str,
    model_connection: dict,
    model: str,
) -> None:
    settings = await get_memory_settings()
    if (
        not settings["enabled"]
        or not settings["tool_enabled"]
        or not settings["background_review_enabled"]
        or not assistant_reply.strip()
    ):
        return
    if message_id in _reviewed_messages:
        return
    user_turns = sum(1 for message in conversation_messages if message.get("role") == "user")
    if user_turns <= 0 or user_turns % int(settings["review_interval_turns"]) != 0:
        return
    _reviewed_messages.add(message_id)
    asyncio.create_task(
        run_memory_review(
            user_id=user_id,
            workspace=workspace,
            conversation_messages=list(conversation_messages),
            assistant_reply=assistant_reply,
            model_connection=dict(model_connection),
            model=model,
        )
    )


async def run_memory_review(
    *,
    user_id: str,
    workspace: str,
    conversation_messages: list[dict[str, Any]],
    assistant_reply: str,
    model_connection: dict,
    model: str,
) -> None:
    try:
        from cptr.utils.ai import chat_completion
        from cptr.utils.chat_task import _default_base_url
        from cptr.utils.config import _get_jwt_secret
        from cptr.utils.crypto import decrypt_key
        from cptr.utils.json_parser import extract_json

        memory_state = await read_memory_state(user_id, workspace)
        transcript = summarize_recent_conversation(conversation_messages, assistant_reply)
        prompt = build_memory_review_prompt(memory_state, workspace, transcript)
        provider = model_connection["provider"]
        api_key = decrypt_key(model_connection.get("api_key", ""), _get_jwt_secret())
        base_url = model_connection.get("base_url") or _default_base_url(provider)
        text = await chat_completion(
            provider=provider,
            base_url=base_url,
            api_key=api_key,
            model=model,
            messages=[{"role": "user", "content": prompt}],
            system="You are cptr's private memory reviewer. Return only valid JSON.",
            max_tokens=700,
            api_type=model_connection.get("api_type", "chat_completions"),
        )
        parsed = extract_json(text)
        if not isinstance(parsed, dict):
            return
        for scope in ("user", "workspace"):
            operations = parsed.get(scope) or []
            if not isinstance(operations, list) or not operations:
                continue
            await remember(
                user_id=user_id,
                workspace=workspace,
                scope=scope,
                operations=operations,
            )
    except Exception:
        return
