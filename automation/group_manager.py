"""Group and team management for phone farm operations."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from wizard.wizard_paths import app_data_root

logger = logging.getLogger(__name__)
_DEFAULT_GROUPS = app_data_root() / "groups.json"


def _default_phone_ent(name: str = "") -> dict[str, Any]:
    return {
        "name": name,
        "sequence_playlist": [],
        "sequence_playlist_secondary": [],
        "sequence_playlist_mode": "ordered",
        "sequence_playlist_shuffle": "none",
        "hits_per_day": 0,
        "steps": [],
    }


@dataclass
class PhoneGroup:
    name: str
    phones: list[str] = field(default_factory=list)
    sequence: str = ""
    schedule_cron: str = ""
    tor_enabled: bool = True
    repeat: int = 1
    repeat_forever: bool = False
    stagger_seconds: float = 0.0
    shuffle: bool = False
    phone_entries: dict[str, dict[str, Any]] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def ensure_phone_entry(self, phone: str) -> dict[str, Any]:
        if phone not in self.phone_entries:
            self.phone_entries[phone] = _default_phone_ent(phone)
        ent = self.phone_entries[phone]
        ent.setdefault("name", phone)
        ent.setdefault("sequence_playlist", [])
        ent.setdefault("sequence_playlist_secondary", [])
        ent.setdefault("sequence_playlist_mode", "ordered")
        ent.setdefault("sequence_playlist_shuffle", "none")
        ent.setdefault("hits_per_day", 0)
        ent.setdefault("steps", [])
        return ent


class GroupManager:
    """Manage phone groups/teams for batch operations and scheduling."""

    def __init__(self, data_path: Path | None = None) -> None:
        self.data_path = data_path or _DEFAULT_GROUPS
        self.groups: dict[str, PhoneGroup] = {}
        self._load()

    def reload(self) -> None:
        """Re-read groups from disk (e.g. after another process wrote groups.json)."""
        self.groups.clear()
        self._load()

    def _load(self) -> None:
        if not self.data_path.is_file():
            return
        try:
            raw = json.loads(self.data_path.read_text(encoding="utf-8"))
            for name, g in raw.items():
                phones = list(g.get("phones", []))
                entries_raw = g.get("phone_entries") or g.get("phones_map") or {}
                phone_entries: dict[str, dict[str, Any]] = {}
                if isinstance(entries_raw, dict):
                    for key, val in entries_raw.items():
                        if isinstance(val, dict):
                            phone_entries[str(key)] = dict(val)
                group = PhoneGroup(
                    name=name,
                    phones=phones,
                    sequence=g.get("sequence", ""),
                    schedule_cron=g.get("schedule_cron", ""),
                    tor_enabled=g.get("tor_enabled", True),
                    repeat=int(g.get("repeat", 1) or 1),
                    repeat_forever=bool(g.get("repeat_forever", False)),
                    stagger_seconds=float(g.get("stagger_seconds", 0) or 0),
                    shuffle=bool(g.get("shuffle", False)),
                    phone_entries=phone_entries,
                    metadata=g.get("metadata", {}) or {},
                )
                for phone in phones:
                    group.ensure_phone_entry(phone)
                self.groups[name] = group
        except (json.JSONDecodeError, OSError, TypeError, ValueError) as exc:
            logger.warning("Failed to load groups: %s", exc)

    def save(self) -> None:
        self.data_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            name: {
                "phones": g.phones,
                "sequence": g.sequence,
                "schedule_cron": g.schedule_cron,
                "tor_enabled": g.tor_enabled,
                "repeat": g.repeat,
                "repeat_forever": g.repeat_forever,
                "stagger_seconds": g.stagger_seconds,
                "shuffle": g.shuffle,
                "phone_entries": g.phone_entries,
                "metadata": g.metadata,
            }
            for name, g in self.groups.items()
        }
        self.data_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def create_group(self, name: str, phones: list[str] | None = None) -> PhoneGroup:
        phones = phones or []
        group = PhoneGroup(name=name, phones=list(phones))
        for phone in phones:
            group.ensure_phone_entry(phone)
        self.groups[name] = group
        self.save()
        return group

    def update_group(
        self,
        name: str,
        *,
        phones: list[str] | None = None,
        sequence: str | None = None,
        schedule_cron: str | None = None,
        tor_enabled: bool | None = None,
        repeat: int | None = None,
        repeat_forever: bool | None = None,
        stagger_seconds: float | None = None,
        shuffle: bool | None = None,
        phone_entries: dict[str, dict[str, Any]] | None = None,
    ) -> PhoneGroup:
        group = self.groups.get(name)
        if not group:
            raise KeyError(f"Group not found: {name}")
        if phones is not None:
            group.phones = list(phones)
            for phone in group.phones:
                group.ensure_phone_entry(phone)
        if sequence is not None:
            group.sequence = sequence
        if schedule_cron is not None:
            group.schedule_cron = schedule_cron
        if tor_enabled is not None:
            group.tor_enabled = tor_enabled
        if repeat is not None:
            group.repeat = max(1, int(repeat))
        if repeat_forever is not None:
            group.repeat_forever = bool(repeat_forever)
        if stagger_seconds is not None:
            group.stagger_seconds = max(0.0, float(stagger_seconds))
        if shuffle is not None:
            group.shuffle = bool(shuffle)
        if phone_entries is not None:
            group.phone_entries = {str(k): dict(v) for k, v in phone_entries.items()}
            for phone in group.phones:
                group.ensure_phone_entry(phone)
        self.save()
        return group

    def add_phone(self, group_name: str, phone_name: str) -> None:
        group = self.groups.get(group_name)
        if not group:
            raise KeyError(f"Group not found: {group_name}")
        if phone_name not in group.phones:
            group.phones.append(phone_name)
            group.ensure_phone_entry(phone_name)
            self.save()

    def remove_phone(self, group_name: str, phone_name: str) -> None:
        group = self.groups.get(group_name)
        if group and phone_name in group.phones:
            group.phones.remove(phone_name)
            self.save()

    def delete_group(self, name: str) -> None:
        self.groups.pop(name, None)
        self.save()

    def list_groups(self) -> list[dict[str, Any]]:
        return [
            {
                "name": g.name,
                "phones": g.phones,
                "sequence": g.sequence,
                "schedule_cron": g.schedule_cron,
                "tor_enabled": g.tor_enabled,
                "repeat": g.repeat,
                "repeat_forever": g.repeat_forever,
                "stagger_seconds": g.stagger_seconds,
                "shuffle": g.shuffle,
                "phone_entries": g.phone_entries,
            }
            for g in self.groups.values()
        ]

    def get_group(self, name: str) -> PhoneGroup | None:
        return self.groups.get(name)

    def phone_entry(self, group_name: str, phone: str) -> dict[str, Any]:
        group = self.groups.get(group_name)
        if not group:
            raise KeyError(f"Group not found: {group_name}")
        return group.ensure_phone_entry(phone)
