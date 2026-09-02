"""Built-in farm site targets for operator dash + farm control.

Keeps DabFlow and LoansFlow as first-class selectable farms without
disabling unique-seq / isolation / draw-without-replacement.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from automation.dabflow_site_profile import dabflow_profile, ensure_dabflow_profile
from automation.loansflow_site_profile import (
    LOANSFLOW_CANONICAL,
    LOANSFLOW_TOOLS_URL,
    LOANSFLOW_URL,
    ensure_loansflow_profile,
    loansflow_profile,
)
from automation.site_profile import SiteProfile, load_profile, profile_path, save_profile
from automation.site_sequence_gen import write_profile_sequences
from wizard.farm_control import apply_profile_farm_env
from wizard.wizard_paths import app_data_root, sequences_dir

BUILTIN_SLUGS = ("dabflow", "loansflow")

_LEGACY_LOANSFLOW_HOSTS = (
    "twoskoops707.github.io/loansflow",
    "loansflow.top",
    "loansflow.pages.dev",
)


@dataclass(frozen=True)
class FarmSiteInfo:
    slug: str
    display_name: str
    url: str
    adapter: str
    sequence_root: str
    sequence_count: int
    path1_count: int
    path2_count: int
    path3_count: int
    daily_visits_csv: str
    daily_ads_csv: str
    impressions_per_visit: float
    ntfy_topic: str
    unique_sequences: bool
    notes: str
    monetization: str  # mantis | adsense | none

    def to_dict(self) -> dict[str, Any]:
        return {
            "slug": self.slug,
            "display_name": self.display_name,
            "url": self.url,
            "adapter": self.adapter,
            "sequence_root": self.sequence_root,
            "sequence_count": self.sequence_count,
            "path1_count": self.path1_count,
            "path2_count": self.path2_count,
            "path3_count": self.path3_count,
            "daily_visits_csv": self.daily_visits_csv,
            "daily_ads_csv": self.daily_ads_csv,
            "impressions_per_visit": self.impressions_per_visit,
            "ntfy_topic": self.ntfy_topic,
            "unique_sequences": self.unique_sequences,
            "notes": self.notes,
            "monetization": self.monetization,
            "tools_url": LOANSFLOW_TOOLS_URL if self.slug == "loansflow" else "",
            "canonical_url": LOANSFLOW_CANONICAL if self.slug == "loansflow" else self.url,
        }


def _seq_counts(root: Path) -> tuple[int, int, int, int]:
    if not root.is_dir():
        return 0, 0, 0, 0
    files = [
        p
        for p in root.glob("*.json")
        if p.name not in {"_generated.json", "_launch.json"} and not p.name.startswith("_")
    ]
    total = len(files)
    p3 = sum(1 for p in files if "_path3_" in p.stem or p.stem.endswith("_ad"))
    p2 = sum(1 for p in files if "_path2_" in p.stem)
    p1 = max(0, total - p2 - p3)
    return total, p1, p2, p3


def _budgets_from_csv(visits_csv: str, ads_csv: str, phones: list[str]) -> dict[str, dict[str, int]]:
    vparts = [p.strip() for p in str(visits_csv or "").split(",") if p.strip()]
    aparts = [p.strip() for p in str(ads_csv or "").split(",") if p.strip()]
    out: dict[str, dict[str, int]] = {}
    for i, phone in enumerate(phones):
        try:
            visits = max(
                0,
                int(float(vparts[i] if i < len(vparts) else (vparts[-1] if vparts else 100))),
            )
        except (TypeError, ValueError, IndexError):
            visits = 100
        try:
            ads = max(
                0,
                int(float(aparts[i] if i < len(aparts) else (aparts[-1] if aparts else 2))),
            )
        except (TypeError, ValueError, IndexError):
            ads = 2
        out[phone] = {"visits": visits, "ads": ads}
    return out


def seed_builtin_profiles(app_data: Path | None = None) -> dict[str, Path]:
    """Ensure DabFlow + LoansFlow profiles exist under app data."""
    root = app_data or app_data_root()
    paths = {
        "dabflow": ensure_dabflow_profile(root),
        "loansflow": ensure_loansflow_profile(root),
    }
    migrate_loansflow_urls(root)
    return paths


def migrate_loansflow_urls(app_data: Path | None = None) -> bool:
    """Point an existing LoansFlow profile at loansflow.loan without wiping budgets."""
    root = app_data or app_data_root()
    path = profile_path(root, "loansflow")
    if not path.is_file():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return False
    if not isinstance(data, dict):
        return False
    url = str(data.get("url") or "").lower()
    if "loansflow.loan" in url and not any(h in url for h in _LEGACY_LOANSFLOW_HOSTS):
        return False
    data["url"] = LOANSFLOW_URL
    notes = str(data.get("notes") or "")
    if not notes or any(h in notes.lower() for h in ("github.io", "loansflow.top")):
        data["notes"] = (
            "LoansFlow calculator suite. Production: https://loansflow.loan/ "
            "(fallback https://loansflow.pages.dev/). "
            "Ads placeholders until AdSense approve — farm warms traffic/SEO first."
        )
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return True


def load_farm_profile(slug: str, app_data: Path | None = None) -> SiteProfile:
    """Load a built-in or saved site profile; fall back to built-in constructors."""
    root = app_data or app_data_root()
    seed_builtin_profiles(root)
    key = (slug or "dabflow").strip().lower() or "dabflow"
    try:
        return load_profile(root, key)
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        if key == "loansflow":
            return loansflow_profile()
        return dabflow_profile()


def sequence_root_for(profile: SiteProfile) -> Path:
    """DabFlow uses the curated base catalog; other sites use sequences/<slug>/."""
    if profile.adapter == "dabflow" or profile.slug == "dabflow":
        return sequences_dir()
    return sequences_dir() / profile.slug


def site_info(slug: str, *, phones: list[str] | None = None) -> FarmSiteInfo:
    del phones  # reserved for future per-phone overlays
    profile = load_farm_profile(slug)
    root = sequence_root_for(profile)
    if profile.slug == "dabflow":
        total, p1, p2, p3 = _seq_counts(root / "base")
        if total == 0:
            total, p1, p2, p3 = _seq_counts(root)
    else:
        total, p1, p2, p3 = _seq_counts(root)
    if profile.adapter == "dabflow":
        monetization = "mantis"
    elif profile.slug == "loansflow":
        monetization = "adsense"
    else:
        monetization = "none"
    return FarmSiteInfo(
        slug=profile.slug,
        display_name=profile.display_name,
        url=profile.url
        or (LOANSFLOW_URL if profile.slug == "loansflow" else "https://getdabflow.app/"),
        adapter=profile.adapter,
        sequence_root=str(root),
        sequence_count=total,
        path1_count=p1,
        path2_count=p2,
        path3_count=p3,
        daily_visits_csv=str(profile.farm.daily_visits_csv or ""),
        daily_ads_csv=str(profile.farm.daily_ads_csv or ""),
        impressions_per_visit=float(profile.farm.impressions_per_visit or 0),
        ntfy_topic=str(profile.farm.ntfy_topic or ""),
        unique_sequences=bool(profile.humanize.concurrent_unique_sequences),
        notes=str(profile.notes or ""),
        monetization=monetization,
    )


def list_farm_sites(*, phones: list[str] | None = None) -> list[dict[str, Any]]:
    seed_builtin_profiles()
    return [site_info(slug, phones=phones).to_dict() for slug in BUILTIN_SLUGS]


def apply_site_to_panel(
    panel: dict[str, Any],
    slug: str,
    *,
    reset_budgets: bool = True,
) -> dict[str, Any]:
    """Stamp panel + env for the selected farm site. Never turns unique-seq off."""
    profile = load_farm_profile(slug)
    apply_profile_farm_env(profile)
    panel = dict(panel)
    panel["active_site_slug"] = profile.slug
    env = dict(panel.get("env") or {})
    for key in (
        "CPHARM_SITE_SLUG",
        "CPHARM_FARM_SEQUENCE_ROOT",
        "CPHARM_FARM_UNIQUE_SEQ",
        "CPHARM_FARM_DAILY_VISITS",
        "CPHARM_FARM_DAILY_ADS",
        "CPHARM_FARM_ALLOW_ADS",
        "CPHARM_NTFY_TOPIC",
        "CPHARM_NTFY_INTERVAL_S",
        "CPHARM_FARM_PHONE_COUNT",
        "CPHARM_FARM_START_STAGGER_BAND",
        "CPHARM_FARM_START_STAGGER_WINDOW",
        "CPHARM_FARM_START_STAGGER_MIN_GAP",
        "CPHARM_FARM_START_STAGGER_JITTER",
        "CPHARM_FARM_IMPRESSIONS_PER_VISIT",
        "CPHARM_FARM_PATH3_DAILY_CAP",
        "CPHARM_FARM_EST_IMPRESSIONS",
        "CPHARM_REQUIRE_UNIQUE_EXIT_IP",
        "CPHARM_ALLOW_SEQUENCE_RUNS",
    ):
        val = os.environ.get(key)
        if val is not None and val != "":
            env[key] = str(val)
    env["CPHARM_FARM_UNIQUE_SEQ"] = "1"
    env["CPHARM_REQUIRE_UNIQUE_EXIT_IP"] = env.get("CPHARM_REQUIRE_UNIQUE_EXIT_IP") or "1"
    env["CPHARM_SITE_SLUG"] = profile.slug
    if profile.adapter == "dabflow":
        env.pop("CPHARM_FARM_SEQUENCE_ROOT", None)
    else:
        env["CPHARM_FARM_SEQUENCE_ROOT"] = str(sequence_root_for(profile))
    if profile.farm.ntfy_topic:
        env["CPHARM_NTFY_TOPIC"] = str(profile.farm.ntfy_topic)
    panel["env"] = env
    phones = [p for p in (panel.get("phones") or []) if isinstance(p, str)]
    if not phones:
        phones = [f"vm{i}.gmadoa" for i in range(4)]
    if reset_budgets:
        panel["budgets"] = _budgets_from_csv(
            profile.farm.daily_visits_csv,
            profile.farm.daily_ads_csv,
            phones,
        )
    info = site_info(profile.slug, phones=phones)
    panel["site"] = info.to_dict()
    if profile.slug == "loansflow":
        panel["notes"] = (
            "LoansFlow farm · https://loansflow.loan/ · unique-seq ON · "
            "ntfy twskoops · AdSense warming (ca-pub-7523216981025331)"
        )
    return panel


def regenerate_loansflow_sequences(
    *,
    out_dir: Path | None = None,
    also_save_profile: bool = True,
) -> dict[str, Any]:
    """Rewrite LoansFlow sequences against https://loansflow.loan/."""
    profile = loansflow_profile()
    app_data = app_data_root()
    if also_save_profile:
        save_profile(app_data, profile)
        repo_mirror = Path(__file__).resolve().parent / "sites" / "sites" / "loansflow"
        repo_mirror.mkdir(parents=True, exist_ok=True)
        (repo_mirror / "profile.json").write_text(
            json.dumps(profile.to_dict(), indent=2) + "\n",
            encoding="utf-8",
        )
    repo_parent = Path(__file__).resolve().parent / "recordings" / "sequences"
    target_parent = out_dir or repo_parent
    count = write_profile_sequences(profile, target_parent, clean=False)
    runtime_parent = sequences_dir()
    if runtime_parent.resolve() != target_parent.resolve():
        write_profile_sequences(profile, runtime_parent, clean=False)
    launch = {
        "slug": "loansflow",
        "url": LOANSFLOW_URL,
        "tools_url": LOANSFLOW_TOOLS_URL,
        "count": count,
        "profile": str(profile_path(app_data, "loansflow")),
        "out": str(target_parent / "loansflow"),
        "runtime_out": str(runtime_parent / "loansflow"),
        "notes": profile.notes,
    }
    for parent in {target_parent, runtime_parent}:
        out = parent / "loansflow"
        out.mkdir(parents=True, exist_ok=True)
        (out / "_launch.json").write_text(json.dumps(launch, indent=2) + "\n", encoding="utf-8")
    return {
        "ok": True,
        "count": count,
        "out": str(target_parent / "loansflow"),
        "runtime_out": str(runtime_parent / "loansflow"),
        "url": LOANSFLOW_URL,
    }
