from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

import bcrypt


class UserAlreadyExists(Exception):
    """Raised when attempting to register an existing username."""


class InvalidCredentials(Exception):
    """Raised when username/password combination is invalid."""


@dataclass(slots=True)
class UserRecord:
    user_id: str
    username: str
    username_lower: str
    password_hash: str
    created_at: str

    def to_dict(self) -> Dict[str, str]:
        return {
            "id": self.user_id,
            "username": self.username,
            "username_lower": self.username_lower,
            "password_hash": self.password_hash,
            "created_at": self.created_at,
        }


class UserStore:
    """Simple file-backed user directory for the MinerU web API."""

    def __init__(self, storage_path: Path) -> None:
        self._path = storage_path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()
        self._users_by_name: Dict[str, UserRecord] = {}
        self._users_by_id: Dict[str, UserRecord] = {}
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            with self._path.open("r", encoding="utf-8") as fp:
                raw = json.load(fp)
        except Exception:
            return
        for item in raw if isinstance(raw, list) else []:
            try:
                record = UserRecord(
                    user_id=item["id"],
                    username=item["username"],
                    username_lower=item.get("username_lower", item["username"].lower()),
                    password_hash=item["password_hash"],
                    created_at=item.get("created_at", datetime.now(timezone.utc).isoformat()),
                )
            except KeyError:
                continue
            self._users_by_name[record.username_lower] = record
            self._users_by_id[record.user_id] = record

    def _dump(self) -> None:
        data = [record.to_dict() for record in self._users_by_id.values()]
        tmp_path = self._path.with_suffix(".tmp")
        with tmp_path.open("w", encoding="utf-8") as fp:
            json.dump(data, fp, ensure_ascii=False, indent=2)
        tmp_path.replace(self._path)

    async def register_user(self, username: str, password: str) -> UserRecord:
        username = username.strip()
        if len(username) < 3:
            raise ValueError("用户名至少 3 个字符")
        if len(password) < 6:
            raise ValueError("密码长度至少 6 位")
        key = username.lower()
        async with self._lock:
            if key in self._users_by_name:
                raise UserAlreadyExists(username)
            user_id = uuid.uuid4().hex
            password_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
            record = UserRecord(
                user_id=user_id,
                username=username,
                username_lower=key,
                password_hash=password_hash,
                created_at=datetime.now(timezone.utc).isoformat(),
            )
            self._users_by_name[key] = record
            self._users_by_id[user_id] = record
            self._dump()
            return record

    async def authenticate_user(self, username: str, password: str) -> UserRecord:
        username = username.strip()
        key = username.lower()
        async with self._lock:
            record = self._users_by_name.get(key)
        if record is None:
            raise InvalidCredentials(username)
        if not bcrypt.checkpw(password.encode("utf-8"), record.password_hash.encode("utf-8")):
            raise InvalidCredentials(username)
        return record

    async def get_user_by_id(self, user_id: str) -> Optional[UserRecord]:
        async with self._lock:
            return self._users_by_id.get(user_id)

    def get_user_by_id_sync(self, user_id: str) -> Optional[UserRecord]:
        return self._users_by_id.get(user_id)


__all__ = [
    "UserStore",
    "UserAlreadyExists",
    "InvalidCredentials",
    "UserRecord",
]
