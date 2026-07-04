"""Persisted, admin-managed list of allowed Telegram user IDs.

Replaces the env-only BOT_ALLOWED_USERS list: on first run the file is
seeded from that env value, then the file becomes authoritative and the
admin manages it from inside the bot (Sozlamalar -> Foydalanuvchilar).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, List


class AllowedUsersStore:
    def __init__(self, admin_id: int, path: Path, seed: Iterable[int] = ()) -> None:
        self.admin_id = admin_id
        self._path = path
        self._ids: set[int] = set()
        self._load(seed)

    def _load(self, seed: Iterable[int]) -> None:
        if self._path.exists():
            try:
                data = json.loads(self._path.read_text(encoding="utf-8"))
                self._ids = {int(x) for x in data}
                return
            except (json.JSONDecodeError, ValueError, OSError):
                pass  # buzilgan/o'qilmaydigan fayl — urug'dan qayta boshlanadi
        self._ids = {int(x) for x in seed}
        self._save()

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(sorted(self._ids)), encoding="utf-8")

    def is_allowed(self, user_id: int) -> bool:
        return user_id == self.admin_id or user_id in self._ids

    def list_ids(self) -> List[int]:
        return sorted(self._ids)

    def add(self, user_id: int) -> bool:
        if user_id == self.admin_id or user_id in self._ids:
            return False
        self._ids.add(user_id)
        self._save()
        return True

    def remove(self, user_id: int) -> bool:
        if user_id not in self._ids:
            return False
        self._ids.discard(user_id)
        self._save()
        return True
