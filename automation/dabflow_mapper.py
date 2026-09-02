"""DabFlow screen mapper — loads getdabflow.app element coordinates at 900x1600."""

from __future__ import annotations

import json
from dataclasses import dataclass
from math import factorial, perm
from pathlib import Path
from typing import Any

from automation.config import BROWSER_PATH12_WEIGHTS

MAPPING_FILE = Path(__file__).resolve().parent / "dabflow_mapping.json"


@dataclass(frozen=True)
class TapPoint:
    x: int
    y: int
    label: str = ""
    selector: str = ""


@dataclass(frozen=True)
class DabFlowMapping:
    base_w: int
    base_h: int
    url: str
    timer_heat_seconds: int
    timer_cool_seconds_min: int
    timer_total_seconds: int
    timer_halfway_seconds: int
    materials: tuple[str, ...]
    concentrates: tuple[str, ...]
    heaters: tuple[str, ...]
    tabs: tuple[str, ...]
    browse_tabs: tuple[str, ...]
    sequence_types: tuple[str, ...]
    home_ad_slot_count: int
    tab_ad_slot_count: int
    screens: dict[str, Any]
    selectors: dict[str, str]

    def material_point(self, material: str) -> TapPoint:
        data = self.screens["home_material"][material]
        return TapPoint(data["x"], data["y"], data.get("label", material), data.get("selector", ""))

    def concentrate_point(self, concentrate: str) -> TapPoint:
        data = self.screens["concentration"][concentrate]
        return TapPoint(data["x"], data["y"], concentrate)

    def heater_point(self, heater: str) -> TapPoint:
        data = self.screens["heating_element"][heater]
        return TapPoint(data["x"], data["y"], heater, data.get("selector", ""))

    def tab_point(self, tab: str) -> TapPoint:
        data = self.screens["tabs"][tab]
        return TapPoint(data["x"], data["y"], data.get("label", tab))

    def age_gate_consent(self) -> TapPoint:
        data = self.screens["age_gate"]["consent_button"]
        return TapPoint(data["x"], data["y"], data.get("label", "consent"))

    def timer_start(self) -> TapPoint:
        data = self.screens["timer"]["start"]
        return TapPoint(data["x"], data["y"], data.get("label", "start"))

    def session_notes_skip(self) -> TapPoint:
        data = self.screens["timer"].get("session_notes_skip") or {"x": 229, "y": 1201}
        return TapPoint(data["x"], data["y"], data.get("label", "session_notes_skip"))

    def start_reveal_scroll(self) -> dict[str, int]:
        data = self.screens["timer"].get("start_reveal_scroll") or {
            "x1": 450,
            "y1": 1150,
            "x2": 450,
            "y2": 550,
            "duration_ms": 420,
        }
        return {
            "x1": int(data["x1"]),
            "y1": int(data["y1"]),
            "x2": int(data["x2"]),
            "y2": int(data["y2"]),
            "duration_ms": int(data.get("duration_ms", 420)),
        }

    def home_ad_slot(self, index: int) -> dict[str, Any]:
        slots = self.screens.get("ads", {}).get("home_slots") or []
        if not slots:
            return {"index": index, "scrolls_before": 2, "x": 450, "y": 900}
        return dict(slots[index % len(slots)])

    def tab_ad_slot(self, tab: str, index: int) -> dict[str, Any]:
        by_tab = self.screens.get("ads", {}).get("tab_slots") or {}
        slots = by_tab.get(tab) or by_tab.get("stats") or []
        if not slots:
            return {"index": index, "scrolls_before": 1, "x": 449, "y": 800}
        return dict(slots[index % len(slots)])

    def ad_banner(self) -> TapPoint:
        data = self.screens["ads"]["post_timer"]
        return TapPoint(data["x"], data["y"], "post_timer_ad")

    def home_ad(self) -> TapPoint:
        data = self.screens["ads"]["home_banner"]
        return TapPoint(data["x"], data["y"], data.get("label", "home_ad"))

    def post_timer_ad(self) -> TapPoint:
        data = self.screens["ads"]["post_timer"]
        return TapPoint(data["x"], data["y"], data.get("label", "post_timer_ad"))

    def tab_ad(self, tab: str) -> TapPoint:
        slot = self.tab_ad_slot(tab, 0)
        return TapPoint(int(slot["x"]), int(slot["y"]), f"tab_ad_{tab}")

    def scroll_swipe(self) -> dict[str, int]:
        start = self.screens["scroll"]["content_start"]
        end = self.screens["scroll"]["content_end"]
        return {"x1": start["x"], "y1": start["y"], "x2": end["x"], "y2": end["y"]}

    def selection_core_count(self) -> int:
        return len(self.materials) * len(self.concentrates) * len(self.heaters)

    def paths_per_selection(self) -> int:
        """Path1 A-D + Path2 (× browsers) + Path3 A-D with home/tab ad fan-out.

        Path1/2 are emitted once per browser (chromium/firefox/brave/duckduckgo).
        Path3 stays Chromium-only for Mantis CDP.
        """
        b = len(self.browse_tabs)
        p1 = 1 + b + perm(b, 2) + factorial(b)
        p2 = 1
        browsers = max(1, len(BROWSER_PATH12_WEIGHTS))
        h = self.home_ad_slot_count
        t = self.tab_ad_slot_count
        p3 = h + (b * t) + (perm(b, 2) * 2 * t) + (factorial(b) * b * t)
        return (p1 + p2) * browsers + p3

    def combination_count(self) -> int:
        return self.selection_core_count() * self.paths_per_selection()

    def to_export_dict(self) -> dict[str, Any]:
        return {
            "source": "getdabflow.app",
            "base_w": self.base_w,
            "base_h": self.base_h,
            "url": self.url,
            "timer": {
                "heat_seconds_default": self.timer_heat_seconds,
                "cool_seconds_min": self.timer_cool_seconds_min,
                "total_seconds_typical": self.timer_total_seconds,
                "halfway_seconds": self.timer_halfway_seconds,
            },
            "options": {
                "materials": list(self.materials),
                "concentrates": list(self.concentrates),
                "heaters": list(self.heaters),
                "tabs": list(self.tabs),
                "browse_tabs": list(self.browse_tabs),
                "sequence_types": list(self.sequence_types),
                "home_ad_slot_count": self.home_ad_slot_count,
                "tab_ad_slot_count": self.tab_ad_slot_count,
            },
            "screens": self.screens,
            "selectors": self.selectors,
            "combination_count": self.combination_count(),
        }


def load_mapping(path: Path | None = None) -> DabFlowMapping:
    """Load DabFlow coordinate mapping from JSON."""
    src = path or MAPPING_FILE
    data = json.loads(src.read_text(encoding="utf-8"))
    timer = data.get("timer", {})
    options = data.get("options", {})
    browse = options.get("browse_tabs") or ["stats", "glass_art", "settings"]
    return DabFlowMapping(
        base_w=int(data.get("base_w", 900)),
        base_h=int(data.get("base_h", 1600)),
        url=str(data.get("url", "https://getdabflow.app")),
        timer_heat_seconds=int(timer.get("heat_seconds_default", 60)),
        timer_cool_seconds_min=int(timer.get("cool_seconds_min", 50)),
        timer_total_seconds=int(timer.get("total_seconds_typical", 110)),
        timer_halfway_seconds=int(timer.get("halfway_seconds", 55)),
        materials=tuple(options.get("materials", [])),
        concentrates=tuple(options.get("concentrates", [])),
        heaters=tuple(options.get("heaters", [])),
        tabs=tuple(options.get("tabs", [])),
        browse_tabs=tuple(browse),
        sequence_types=tuple(options.get("sequence_types", [])),
        home_ad_slot_count=int(options.get("home_ad_slot_count", 4)),
        tab_ad_slot_count=int(options.get("tab_ad_slot_count", 2)),
        screens=data.get("screens", {}),
        selectors=data.get("selectors", {}),
    )


def export_mapping(path: Path, mapping: DabFlowMapping | None = None) -> Path:
    """Write mapping JSON to disk."""
    payload = (mapping or load_mapping()).to_export_dict()
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def selector_to_point(selector: str, mapping: DabFlowMapping | None = None) -> TapPoint | None:
    """Resolve a CSS selector hint to a tap point when known."""
    m = mapping or load_mapping()
    for screen_name, screen in m.screens.items():
        if not isinstance(screen, dict):
            continue
        for key, val in screen.items():
            if isinstance(val, dict) and val.get("selector") == selector:
                return TapPoint(val["x"], val["y"], key, selector)
    return None
