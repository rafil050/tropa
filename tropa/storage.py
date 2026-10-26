"""Сохранение серверов, подписок и настроек в JSON-файл."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from .models import Profile, Settings, Subscription
from .paths import data_dir


class Store:
    FILE_NAME = "state.json"

    def __init__(self, path: Path | None = None):
        self.path = path or (data_dir() / self.FILE_NAME)
        self.settings = Settings()
        self.profiles: list[Profile] = []
        self.subscriptions: list[Subscription] = []
        self.selected_id: str = ""
        self.load()

    # ------------------------------------------------------------ файл

    def load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text("utf-8"))
        except (OSError, json.JSONDecodeError):
            # повреждённый файл не удаляем — сохраним копию, чтобы ничего не потерять
            try:
                self.path.replace(self.path.with_suffix(".broken.json"))
            except OSError:
                pass
            return
        self.settings = Settings.from_dict(data.get("settings", {}))
        self.profiles = [Profile.from_dict(p) for p in data.get("profiles", []) if isinstance(p, dict) and p.get("protocol")]
        self.subscriptions = [Subscription.from_dict(s) for s in data.get("subscriptions", []) if isinstance(s, dict) and s.get("url")]
        self.selected_id = data.get("selected_id", "")

    def save(self) -> None:
        data = {
            "version": 1,
            "settings": self.settings.to_dict(),
            "subscriptions": [s.to_dict() for s in self.subscriptions],
            "profiles": [p.to_dict() for p in self.profiles],
            "selected_id": self.selected_id,
        }
        # пишем во временный файл и подменяем — так файл не испортится при сбое
        fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), prefix=".state-", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=1)
            os.replace(tmp, self.path)
        except OSError:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    # ------------------------------------------------------------ профили

    def profile(self, profile_id: str) -> Profile | None:
        return next((p for p in self.profiles if p.id == profile_id), None)

    def selected(self) -> Profile | None:
        return self.profile(self.selected_id)

    def add_profiles(self, profiles: list[Profile]) -> int:
        """Добавляет вручную импортированные профили, пропуская точные дубли. Возвращает число добавленных."""
        existing = {p.key() for p in self.profiles if not p.sub_id}
        added: list[Profile] = []
        for p in profiles:
            if p.key() in existing:
                continue
            p.sub_id = ""
            self.profiles.append(p)
            existing.add(p.key())
            added.append(p)
        # выбираем первый действительно добавленный: профиль-дубль в список не попал
        if added and not self.selected():
            self.selected_id = added[0].id
        return len(added)

    def remove_profiles(self, ids: set[str]) -> None:
        self.profiles = [p for p in self.profiles if p.id not in ids]
        if self.selected_id in ids:
            self.selected_id = ""

    def replace_subscription_profiles(self, sub_id: str, fresh: list[Profile]) -> None:
        """Обновляет серверы подписки, сохраняя id (и выбор) у тех, что не изменились."""
        old = {p.key(): p for p in self.profiles if p.sub_id == sub_id}
        merged: list[Profile] = []
        seen: set[str] = set()
        for p in fresh:
            key = p.key()
            if key in seen:
                continue
            seen.add(key)
            prev = old.get(key)
            if prev is not None:
                p.id = prev.id
                p.ping = prev.ping
            p.sub_id = sub_id
            merged.append(p)
        # сохраняем порядок: подписка встаёт на место своих старых серверов
        result: list[Profile] = []
        inserted = False
        for p in self.profiles:
            if p.sub_id == sub_id:
                if not inserted:
                    result.extend(merged)
                    inserted = True
                continue
            result.append(p)
        if not inserted:
            result.extend(merged)
        self.profiles = result
        if self.selected_id and not self.selected():
            self.selected_id = ""

    # ------------------------------------------------------------ подписки

    def subscription(self, sub_id: str) -> Subscription | None:
        return next((s for s in self.subscriptions if s.id == sub_id), None)

    def remove_subscription(self, sub_id: str) -> None:
        self.subscriptions = [s for s in self.subscriptions if s.id != sub_id]
        self.remove_profiles({p.id for p in self.profiles if p.sub_id == sub_id})
