"""Generic Site Profile — PharmFlow farms any website/APK; not tied to one brand."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


PROFILE_SCHEMA_VERSION = 2


def _slugify(text: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "_", (text or "").strip().lower()).strip("_")
    return s[:64] or "site"


@dataclass
class GateTap:
    """Optional entry gate (age / cookies / continue)."""

    label: str = "continue"
    x: int = 450
    y: int = 980
    wait_before_s: float = 1.5
    wait_after_s: float = 0.55


@dataclass
class CoreAction:
    """What counts as a successful session."""

    kind: str = "tap"  # tap | wait | scroll_then_tap
    description: str = "Primary action"
    x: int = 450
    y: int = 1200
    scroll_before: bool = False
    confirm_wait_s: float = 2.0


@dataclass
class BrowsePath:
    name: str = "home"
    x: int = 180
    y: int = 1535
    scroll_to_bottom: bool = True
    scroll_swipes: int = 4


@dataclass
class AdClick:
    name: str = "sponsored"
    x: int = 450
    y: int = 1100
    max_per_hour: int = 1
    # When set, Path3 browse uses this swipe count instead of browse_paths[0].scroll_swipes
    # (needed when an in-content slot moves higher and fewer scrolls keep it on-screen).
    scroll_swipes: int | None = None


@dataclass
class HumanizePrefs:
    preset: str = "moderate"  # conservative | moderate | aggressive
    concurrent_unique_sequences: bool = True


@dataclass
class FarmPrefs:
    phone_count: int = 4
    # Legacy hourly fields — ignored when daily_* set (day mode).
    seqs_per_hour: int = 0
    hours: float = 0.0  # 0 = 24h day mode
    allow_ads: bool = True
    ads_per_hour: int = 0
    # Mantis guidance: daily visits / ad clicks (comma CSV per phone).
    daily_visits_csv: str = "173,148,141,119"
    daily_ads_csv: str = "5,4,4,3"
    impressions_per_visit: float = 22.0
    ntfy_topic: str = ""
    ntfy_hourly: bool = True
    ntfy_interval_s: int = 7200
    startup_spread_minutes: int = 2  # money-day: ~120s window, not 30min stagnate


@dataclass
class SiteProfile:
    """Durable description of one farm target (website or APK)."""

    schema_version: int = PROFILE_SCHEMA_VERSION
    slug: str = "site"
    display_name: str = "Untitled site"
    target_kind: str = "website"  # website | app
    adapter: str = "generic"
    url: str = ""
    package: str = ""
    gates: list[GateTap] = field(default_factory=list)
    core: CoreAction = field(default_factory=CoreAction)
    browse_paths: list[BrowsePath] = field(default_factory=list)
    ads: list[AdClick] = field(default_factory=list)
    humanize: HumanizePrefs = field(default_factory=HumanizePrefs)
    farm: FarmPrefs = field(default_factory=FarmPrefs)
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SiteProfile":
        if not isinstance(data, dict):
            raise TypeError("profile must be a dict")
        gates = [GateTap(**g) for g in (data.get("gates") or []) if isinstance(g, dict)]
        core_raw = data.get("core") if isinstance(data.get("core"), dict) else {}
        browse = [BrowsePath(**b) for b in (data.get("browse_paths") or []) if isinstance(b, dict)]
        ads = [AdClick(**a) for a in (data.get("ads") or []) if isinstance(a, dict)]
        hum = data.get("humanize") if isinstance(data.get("humanize"), dict) else {}
        farm = data.get("farm") if isinstance(data.get("farm"), dict) else {}
        slug = str(data.get("slug") or _slugify(str(data.get("display_name") or "site")))
        return cls(
            schema_version=int(data.get("schema_version") or PROFILE_SCHEMA_VERSION),
            slug=slug,
            display_name=str(data.get("display_name") or slug),
            target_kind=str(data.get("target_kind") or "website"),
            adapter=str(data.get("adapter") or "generic"),
            url=str(data.get("url") or ""),
            package=str(data.get("package") or ""),
            gates=gates,
            core=CoreAction(**core_raw) if core_raw else CoreAction(),
            browse_paths=browse,
            ads=ads,
            humanize=HumanizePrefs(**hum) if hum else HumanizePrefs(),
            farm=FarmPrefs(**farm) if farm else FarmPrefs(),
            notes=str(data.get("notes") or ""),
        )


def sites_root(app_data: Path) -> Path:
    d = Path(app_data) / "sites"
    d.mkdir(parents=True, exist_ok=True)
    return d


def profile_path(app_data: Path, slug: str) -> Path:
    return sites_root(app_data) / _slugify(slug) / "profile.json"


def save_profile(app_data: Path, profile: SiteProfile) -> Path:
    profile.slug = _slugify(profile.slug or profile.display_name)
    path = profile_path(app_data, profile.slug)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(profile.to_dict(), indent=2) + "\n", encoding="utf-8")
    return path


def load_profile(app_data: Path, slug: str) -> SiteProfile:
    path = profile_path(app_data, slug)
    data = json.loads(path.read_text(encoding="utf-8"))
    return SiteProfile.from_dict(data)


def list_profiles(app_data: Path) -> list[str]:
    root = sites_root(app_data)
    out: list[str] = []
    for child in sorted(root.iterdir() if root.is_dir() else []):
        if child.is_dir() and (child / "profile.json").is_file():
            out.append(child.name)
    return out


def interview_defaults(*, kind: str = "website", name: str = "", url: str = "", package: str = "") -> SiteProfile:
    """Starter answers for the Site Interview — user edits before generate."""
    display = name.strip() or ("Web site" if kind == "website" else "App")
    return SiteProfile(
        slug=_slugify(display),
        display_name=display,
        target_kind="app" if kind == "app" else "website",
        url=url.strip(),
        package=package.strip(),
        gates=[GateTap(label="age_or_continue", x=380, y=980)],
        core=CoreAction(kind="scroll_then_tap", description="Primary CTA", scroll_before=True),
        browse_paths=[
            BrowsePath(name="tab_a", x=180, y=1535),
            BrowsePath(name="tab_b", x=450, y=1535),
            BrowsePath(name="tab_c", x=720, y=1535),
        ],
        ads=[AdClick(name="sponsored_0", max_per_hour=1)],
        notes="Created from Site Interview — edit coords to match your UI.",
    )
