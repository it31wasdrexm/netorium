from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any


def hash_shared_secret(secret: str, *, label: str = "Signing secret") -> str:
    clean_secret = secret.strip()
    if not clean_secret:
        raise ValueError(f"{label} cannot be empty.")
    return hashlib.sha256(clean_secret.encode("utf-8")).hexdigest()


def build_agent_command_signature(
    *,
    signing_key: str,
    agent_id: str,
    command_id: str,
    command_type: str,
    payload: dict[str, Any],
    created_at: str,
) -> str:
    clean_key = _normalize_text(signing_key, "Signing key")
    message = _canonical_command_message(
        agent_id=agent_id,
        command_id=command_id,
        command_type=command_type,
        payload=payload,
        created_at=created_at,
    )
    return hmac.new(clean_key.encode("utf-8"), message, hashlib.sha256).hexdigest()


def verify_agent_command_signature(
    *,
    signing_key: str,
    agent_id: str,
    command_id: str,
    command_type: str,
    payload: dict[str, Any],
    created_at: str,
    signature: str,
) -> bool:
    if not signature.strip():
        return False
    expected = build_agent_command_signature(
        signing_key=signing_key,
        agent_id=agent_id,
        command_id=command_id,
        command_type=command_type,
        payload=payload,
        created_at=created_at,
    )
    return hmac.compare_digest(expected, signature.strip())


def _canonical_command_message(
    *,
    agent_id: str,
    command_id: str,
    command_type: str,
    payload: dict[str, Any],
    created_at: str,
) -> bytes:
    command = {
        "agent_id": _normalize_text(agent_id, "Agent ID"),
        "command_id": _normalize_text(command_id, "Command ID"),
        "command_type": _normalize_text(command_type, "Command type"),
        "payload": payload,
        "created_at": _normalize_text(created_at, "Command creation timestamp"),
    }
    return json.dumps(
        command,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _normalize_text(value: str, label: str) -> str:
    clean_value = value.strip()
    if not clean_value:
        raise ValueError(f"{label} cannot be empty.")
    return clean_value
