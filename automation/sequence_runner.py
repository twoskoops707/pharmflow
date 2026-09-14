"""Sequence runner with humanization, DabFlow actions, and playlist modes."""

from __future__ import annotations

import json
import logging
import os
import random
import time
import urllib.parse
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from automation.browser_farm import (
    browse_url,
    choose_sequence_browser,
    clear_browser_before_sequence,
    get_sequence_browser,
    is_path3_sequence_name,
    scramble_for_sequence,
    verify_before_browse,
)
from automation.browser_adb import browser_info_for_package
from automation.browser_adb import _dump_ui as dump_browser_ui
from automation.browser_onboarding import dismiss_blocking_browser_overlays
from automation.emulator_ad_mode import (
    ad_checkpoint_from_description,
    ensure_ads_visible_browser_hidden,
    hide_browser_chrome,
    maybe_fallback_ad_open_url,
    pause_tor_for_ads,
    resume_tor_after_ads,
)
from automation.session_notes_uia import (
    dismiss_session_notes_verified,
    step_wants_session_notes_dismiss,
    step_wants_session_notes_gone,
    wait_session_notes_gone,
)
from automation.browser_adb import (
    clear_browser_package,
    clear_chromium_all_data,
    defocus_chromium_omnibox,
    dismiss_chromium_fre,
    launch_app,
    open_url as adb_open_url,
)
from automation.dabflow_overlays import (
    AGE_GATE_POST_YES_SETTLE_S,
    AGE_GATE_YES,
    HOME_SCREEN_WAIT_MAX_S,
    HOME_SCREEN_WAIT_MIN_S,
    dismiss_native_alert,
    ensure_start_perfect_dab,
)
from automation.browse_proxy import (
    browser_package_for_serial,
    guest_proxy_healthy,
    pin_guest_proxy,
    restore_inject_after_identity,
    sync_browse_proxy_env_from_prefs,
)
from automation.config import (
    AUTHOR_HEIGHT,
    AUTHOR_WIDTH,
    BROWSER_CHROMIUM,
    PLAYLIST_ORDERED,
    PLAYLIST_RANDOM,
    PLAYLIST_SERIES,
    REQUIRED_SEQUENCE_VERSION,
    SHUFFLE_BOTH_SEPARATELY,
    SHUFFLE_COMBINED,
    SHUFFLE_NONE,
    SHUFFLE_SET_A,
    SHUFFLE_SET_B,
    is_skip_fingerprint,
    sequences_run_allowed,
)
from automation.sequence_isolation import isolate_before_sequence, isolation_skip_allowed
from automation.ad_slot_pick import nudge_tap_off_ads, pick_live_ad_coords
from automation.dabflow_mantis_ad_urls import (
    has_live_click_token,
    is_mantis_house_bot_click_url,
    phone_viewed_click_url,
)
from automation.dabflow_mantis_client_patch import (
    _ingest_paying_fill_file,
    cdp_creative_tap_targets,
    click_url_for_zone,
    paying_fill_file_fresh,
    prefetch_ssp_ads_prefer_paying,
)
from automation.farm_launch_guard import (
    bring_browser_foreground_dabflow,
    foreground_package,
    should_skip_content_tap,
)
from automation.human_ad_click import human_path3_ad_engage, human_scroll_ad_landing
from automation.mumu_shell_cli import phone_vm_index
from automation.humanize import (
    HumanizeConfig,
    MIN_SAFE_TAP_Y,
    enforce_scroll_coords,
    normalize_swipe_params,
    resolve_coordinate,
    resolve_duration_ms,
    resolve_seconds,
)
from automation.sequence_paths import resolve_sequence_path
from automation.web_viewport import element_center, remap_y
from automation import tor_manager
from wizard.mumu_farm_ops import MuMuFarmOps

logger = logging.getLogger(__name__)

ANDROID_KEY_BACK = 4


def _env_float(name: str, default: float) -> float:
    """Env float with sane floor; missing/bad values fall back to default."""
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return max(0.0, float(raw))
    except ValueError:
        return default


def _inst_phone_idx(inst: Any) -> int:
    """Inject/Tor index = vmN from name (not prefs enumerate slot)."""
    if not inst:
        return 0
    name = str(getattr(inst, "name", "") or "")
    fallback = int(getattr(inst, "index", 0) or 0)
    idx = phone_vm_index(name, fallback)
    if fallback != idx:
        try:
            inst.index = idx
        except Exception:
            pass
    return idx


def _farm_ads_allowed() -> bool:
    """Path3 / ad-tap engage only when operator explicitly allows ads."""
    return os.environ.get("PHARMFLOW_FARM_ALLOW_ADS", "0").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _path3_require_paying() -> bool:
    """Jul 30 billed by opening live ``clicked`` URLs. Skipping 'house' kills the day."""
    return os.environ.get("PHARMFLOW_PATH3_REQUIRE_PAYING", "0").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def is_mantis_clicked_tracking_url(url: str) -> bool:
    """True for a Mantis SSP tracking redirect (the Jul 30 click path)."""
    return "bids.mantis.marketing/clicked" in (url or "").strip().lower()


def is_paying_mantis_click_url(url: str) -> bool:
    """True only for a billable Mantis tracking redirect (never house/bot)."""
    u = (url or "").strip()
    return is_mantis_clicked_tracking_url(u) and not is_mantis_house_bot_click_url(u)


def _fresh_paying_fill_click(zone: str) -> str:
    """File ads only when the shared fill is fresh and the URL has a live bi+bt.

    A stale fill replaces the phone's impression token and pays $0.
    """
    if not paying_fill_file_fresh():
        return ""
    z = str(zone or "")
    try:
        rows = _ingest_paying_fill_file() or []
    except Exception:
        return ""
    for ad in rows:
        click = str(ad.get("click_url") or "").strip()
        if not has_live_click_token(click):
            continue
        ad_zone = str(ad.get("zone_id") or "").strip()
        if z and ad_zone and ad_zone != z:
            continue
        return click
    return ""


def resolve_path3_paying_click_url(zone: str, prefer_click: str = "") -> str:
    """Return a paying SSP click_url, or empty. Never returns house/bot URLs.

    After cache + force_refresh still miss, burst-prefetch paying fill and retry.
    Never returns a URL unless it has a live bi+bt token. File ads only when
    the shared fill is inside the freshness window.
    """
    click = (prefer_click or "").strip()
    if has_live_click_token(click):
        return click
    z = str(zone or "")
    click = click_url_for_zone(z, allow_any=True, prefer_paying=True) or ""
    if has_live_click_token(click):
        return click
    click = (
        click_url_for_zone(
            z, allow_any=True, prefer_paying=True, force_refresh=True
        )
        or ""
    )
    if has_live_click_token(click):
        return click
    try:
        prefetch_ssp_ads_prefer_paying(
            attempts=14, delay_s=0.25, allow_house_fallback=False
        )
    except Exception:
        pass
    click = (
        click_url_for_zone(
            z, allow_any=True, prefer_paying=True, force_refresh=True
        )
        or ""
    )
    if has_live_click_token(click):
        return click
    return _fresh_paying_fill_click(z)


def resolve_path3_click_url(zone: str, prefer_click: str = "") -> str:
    """Open a token-bound ``clicked`` URL. Never a stale or synthetic wrap."""
    raw = (prefer_click or "").strip()
    if has_live_click_token(raw):
        return raw
    z = str(zone or "")
    cached = click_url_for_zone(z, allow_any=True, prefer_paying=True) or ""
    if has_live_click_token(cached):
        return cached
    if not _path3_require_paying():
        any_click = click_url_for_zone(z, allow_any=True, prefer_paying=False) or ""
        if has_live_click_token(any_click):
            return any_click
        return _fresh_paying_fill_click(z)
    return resolve_path3_paying_click_url(zone, prefer_click)


class StepAction(str, Enum):
    TAP = "tap"
    WAIT = "wait"
    SWIPE = "swipe"
    OPEN_URL = "open_url"
    LAUNCH_APP = "launch_app"
    ROTATE_IDENTITY = "rotate_identity"
    CLEAR_COOKIES = "clear_cookies"
    ENSURE_FINGERPRINT = "ensure_fingerprint"
    CLOSE_APP = "close_app"
    SHELL = "shell"
    KEYEVENT = "keyevent"
    KEY = "key"
    BACK = "back"
    TYPE_TEXT = "type_text"
    FULL_RESET = "full_reset"


@dataclass
class SequenceStep:
    action: StepAction
    params: dict[str, Any] = field(default_factory=dict)
    description: str = ""


@dataclass
class Sequence:
    name: str
    phone: str
    steps: list[SequenceStep] = field(default_factory=list)
    author_width: int = AUTHOR_WIDTH
    author_height: int = AUTHOR_HEIGHT
    set_label: str = ""
    humanize: HumanizeConfig = field(default_factory=HumanizeConfig)
    requires_fingerprint: bool = True
    description: str = ""
    sequence_version: int = 0
    preferred_browser: str = ""

    @classmethod
    def from_json(cls, path: Path) -> Sequence:
        data = json.loads(path.read_text(encoding="utf-8"))
        steps: list[SequenceStep] = []
        for s in data.get("steps", []):
            raw_action = s.get("action") or s.get("type") or ""
            try:
                action = StepAction(raw_action)
            except ValueError:
                logger.warning("Unknown step action %r in %s - skipping", raw_action, path.name)
                continue
            steps.append(
                SequenceStep(
                    action=action,
                    params=s.get("params", _legacy_params(s)),
                    description=s.get("description", ""),
                )
            )
        dabflow = data.get("dabflow") if isinstance(data.get("dabflow"), dict) else {}
        preferred = (
            str(data.get("preferred_browser") or "").strip()
            or str(dabflow.get("browser") or "").strip()
        )
        return cls(
            name=data.get("name", path.stem),
            phone=data.get("phone", ""),
            steps=steps,
            author_width=data.get("author_width", data.get("base_w", AUTHOR_WIDTH)),
            author_height=data.get("author_height", data.get("base_h", AUTHOR_HEIGHT)),
            set_label=data.get("set", ""),
            humanize=HumanizeConfig.from_dict(data.get("humanize")),
            requires_fingerprint=bool(data.get("requires_fingerprint", True)),
            description=data.get("description", ""),
            sequence_version=int(data.get("sequence_version", 0)),
            preferred_browser=preferred,
        )


_NAMED_KEYS = {
    "BACK": 4,
    "HOME": 3,
    "MENU": 82,
    "POWER": 26,
    "ENTER": 66,
    "TAB": 61,
    "APP_SWITCH": 187,
}


def _key_code(params: dict[str, Any]) -> int | None:
    """Numeric code or a named Android key. None means the step cannot run."""
    raw = params.get("code", params.get("key", params.get("keycode")))
    if raw is None or raw == "":
        return None
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return raw
    text = str(raw).strip()
    if text.isdigit():
        return int(text)
    return _NAMED_KEYS.get(text.upper())


def _legacy_params(step: dict[str, Any]) -> dict[str, Any]:
    """Support flat step fields from early DabFlow drafts."""
    params = dict(step.get("params", {}))
    for key in (
        "x",
        "y",
        "x1",
        "y1",
        "x2",
        "y2",
        "x_start",
        "y_start",
        "x_end",
        "y_end",
        "seconds",
        "duration_ms",
        "duration",
        "ms",
        "url",
        "command",
        "code",
        "key",
        "package",
        "text",
        "checkpoint",
        "verify_dismiss",
        "until_session_notes_gone",
    ):
        if key in step and key not in params:
            params[key] = step[key]
    if "x_start" in params and "x1" not in params:
        params["x1"] = params.pop("x_start")
    if "y_start" in params and "y1" not in params:
        params["y1"] = params.pop("y_start")
    if "x_end" in params and "x2" not in params:
        params["x2"] = params.pop("x_end")
    if "y_end" in params and "y2" not in params:
        params["y2"] = params.pop("y_end")
    if "duration" in params and "duration_ms" not in params:
        params["duration_ms"] = params.pop("duration")
    if "ms" in params and "duration_ms" not in params:
        params["duration_ms"] = params["ms"]
    return params


@dataclass
class Playlist:
    name: str
    sequences: list[str]
    mode: str = PLAYLIST_ORDERED
    shuffle: str = SHUFFLE_NONE
    phone: str = ""

    @classmethod
    def from_json(cls, path: Path) -> Playlist:
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            name=data.get("name", path.stem),
            sequences=data.get("sequences", []),
            mode=data.get("mode", PLAYLIST_ORDERED),
            shuffle=data.get("shuffle", SHUFFLE_NONE),
            phone=data.get("phone", ""),
        )


class SequenceRunner:
    def __init__(self, farm: MuMuFarmOps) -> None:
        self.farm = farm
        self._cancel = False
        # True when this run already performed full isolation via
        # isolate_before_sequence() — the authored rotate_identity step in every
        # sequence (8k+ files) then re-runs the same work (~60-100s wasted).
        self._iso_done = False
        self._iso_phone = ""

    def cancel(self) -> None:
        self._cancel = True

    def run(self, sequence: Sequence) -> dict[str, Any]:
        self._cancel = False
        self._iso_done = False
        self._iso_phone = ""
        if not sequences_run_allowed():
            return {
                "name": sequence.name,
                "success": False,
                "error": (
                    "Sequence runs are BLOCKED until ad code is verified. "
                    "Set PHARMFLOW_ALLOW_SEQUENCE_RUNS=1 to enable."
                ),
            }
        phone = sequence.phone
        report: dict[str, Any] = {"name": sequence.name, "phone": phone, "steps": [], "success": True}
        inst = self._resolve_phone(phone)
        if not inst:
            self.farm.list_instances()
            time.sleep(0.5)
            inst = self._resolve_phone(phone)
        if not inst:
            return {"name": sequence.name, "success": False, "error": f"Phone {phone} not found"}

        if sequence.sequence_version < REQUIRED_SEQUENCE_VERSION:
            return {
                "name": sequence.name,
                "success": False,
                "error": (
                    f"Sequence '{sequence.name}' is v{sequence.sequence_version} - "
                    f"rewrite required (need v{REQUIRED_SEQUENCE_VERSION}+). "
                    "Run: py scripts/generate_dabflow_sequences.py "
                    "(or Builder → Regenerate all sequences in PharmFlow.exe)"
                ),
            }

        sync_browse_proxy_env_from_prefs()

        # Path3 => Chromium (CDP). Path1/2 use preferred browser unless
        # PHARMFLOW_FARM_BROWSERS / CHROMIUM_ONLY locks to chromium.
        browsers_raw = (os.environ.get("PHARMFLOW_FARM_BROWSERS") or "").strip().lower()
        browser_tags = {p.strip() for p in browsers_raw.split(",") if p.strip()}
        chromium_only = (
            os.environ.get("PHARMFLOW_FARM_CHROMIUM_ONLY") or ""
        ).strip().lower() in ("1", "true", "yes", "on")
        # Path3: allow any MITM-capable browser (Chromium/Brave/Opera) for
        # stealth rotation. Only force Chromium when env explicitly says so.
        # Firefox/DDG skip MITM so they can't paint ads — excluded by weighted select.
        force_chromium = (
            browser_tags == {"chromium"}
            or chromium_only
        )
        skip_iso = isolation_skip_allowed()
        if skip_iso:
            clear_browser_before_sequence(
                self.farm,
                phone,
                force_chromium=force_chromium,
                preferred_package="" if force_chromium else sequence.preferred_browser,
            )
            choose_sequence_browser(
                self.farm,
                phone,
                force_chromium=force_chromium,
                preferred_package="" if force_chromium else sequence.preferred_browser,
            )
            report["isolation"] = {"skipped": True}
            logger.warning("[%s] sequence isolation SKIPPED (demo/verify only)", phone)
        else:
            try:
                iso = isolate_before_sequence(
                    self.farm,
                    phone,
                    force_chromium=force_chromium,
                    preferred_browser="" if force_chromium else sequence.preferred_browser,
                )
                self._iso_done = True
                self._iso_phone = phone
                report["isolation"] = {
                    "ip_before": iso.ip_before,
                    "ip_after": iso.ip_after,
                    "ip_changed": iso.ip_changed,
                    "ip_retries": iso.ip_retries,
                    "geo": iso.geo_label,
                    "geo_tz": iso.geo_tz,
                    "brand": iso.browser_brand,
                    "model": iso.browser_model,
                    "android_id": iso.android_id,
                    "imei": iso.imei,
                    "device_serial": iso.device_serial,
                    "http_proxy": iso.http_proxy,
                }
                chosen = get_sequence_browser(phone)
                if chosen is not None:
                    report["isolation"]["browser"] = chosen.package
                    report["isolation"]["browser_label"] = chosen.label
                    report["browser"] = chosen.package
                report["ip_before"] = iso.ip_before
                report["ip_after"] = iso.ip_after
                report["ip_changed"] = iso.ip_changed
                report["ip_retries"] = iso.ip_retries
            except Exception as exc:
                return {
                    "phone": phone,
                    "name": sequence.name,
                    "success": False,
                    "error": f"sequence isolation failed: {exc}",
                    "failed_at": -1,
                    "ip_changed": False,
                }

        serial = inst.adb_serial
        phone_idx = _inst_phone_idx(inst)
        # Keep screen alive for the full sequence — 60s default timeout killed
        # taps mid-sequence (black screen = ADB tap fail).
        try:
            self.farm.adb.shell(
                "settings put system screen_off_timeout 1800000",
                serial=serial,
            )
            self.farm.adb.shell("input keyevent 224", serial=serial)  # WAKEUP
        except Exception:
            pass
        try:
            for i, step in enumerate(sequence.steps):
                if self._cancel:
                    report["success"] = False
                    report["cancelled_at"] = i
                    break
                # Serial can change after rotate/cold-boot on MuMu ARM (10.0.2.x DHCP).
                inst = self._resolve_phone(phone)
                if inst:
                    serial = inst.adb_serial
                    phone_idx = _inst_phone_idx(inst)
                _t0 = time.monotonic()
                step_result = self._run_step(step, phone, serial, sequence)
                _dt = time.monotonic() - _t0
                step_result["elapsed_s"] = round(_dt, 1)
                logger.info(
                    "[%s] step %02d %-10s %6.1fs %s",
                    phone,
                    i,
                    step_result.get("action") or step.action.value,
                    _dt,
                    (step.description or "")[:46],
                )
                report["steps"].append(step_result)
                if not step_result.get("ok"):
                    report["success"] = False
                    report["failed_at"] = i
                    report["error"] = step_result.get("error") or step_result.get("action")
                    break
        finally:
            # Ad-fill windows clear Tor temporarily; restore for the next sequence.
            try:
                resume_tor_after_ads(self.farm.adb, serial, phone_idx)
            except Exception as exc:
                logger.warning("resume_tor_after_ads soft-fail phone=%s: %s", phone, exc)
            try:
                from automation.browse_proxy import pin_guest_proxy

                pin_guest_proxy(self.farm.adb, serial, int(phone_idx))
            except Exception as exc:
                logger.warning("end-of-seq proxy pin soft-fail phone=%s: %s", phone, exc)
        return report

    def run_playlist(self, playlist: Playlist, sequences_dir: Path) -> dict[str, Any]:
        seqs = self._resolve_playlist_sequences(playlist, sequences_dir)
        reports = []
        for seq in seqs:
            seq.phone = playlist.phone or seq.phone
            r = self.run(seq)
            reports.append(r)
            if playlist.mode == PLAYLIST_SERIES and not r.get("success"):
                break
        return {"playlist": playlist.name, "reports": reports, "success": all(r.get("success") for r in reports)}

    def _resolve_playlist_sequences(self, playlist: Playlist, directory: Path) -> list[Sequence]:
        loaded: list[Sequence] = []
        for name in playlist.sequences:
            try:
                path = resolve_sequence_path(directory, name)
            except FileNotFoundError:
                path = directory / f"{name}.json"
            if path.is_file():
                loaded.append(Sequence.from_json(path))
        if playlist.shuffle == SHUFFLE_SET_A:
            loaded = [s for s in loaded if s.set_label == "set_a"]
        elif playlist.shuffle == SHUFFLE_SET_B:
            loaded = [s for s in loaded if s.set_label == "set_b"]
        elif playlist.shuffle == SHUFFLE_BOTH_SEPARATELY:
            a = [s for s in loaded if s.set_label == "set_a"]
            b = [s for s in loaded if s.set_label == "set_b"]
            random.shuffle(a)
            random.shuffle(b)
            loaded = a + b
        elif playlist.shuffle == SHUFFLE_COMBINED:
            random.shuffle(loaded)
        if playlist.mode == PLAYLIST_RANDOM:
            random.shuffle(loaded)
        return loaded

    def _resolve_phone(self, phone: str) -> Any:
        """Resolve by live VM name, with legacy Phone-N aliases via farm.get_phone."""
        if hasattr(self.farm, "get_phone"):
            return self.farm.get_phone(phone)
        if phone not in self.farm.instances:
            self.farm.list_instances()
        return self.farm.instances.get(phone)

    def _run_step(self, step: SequenceStep, phone: str, serial: str, sequence: Sequence) -> dict[str, Any]:
        action = step.action
        p = step.params
        hz = sequence.humanize
        result: dict[str, Any] = {"action": action.value, "description": step.description}
        try:
            if action == StepAction.TAP:
                desc_lower = step.description.lower()
                is_age_gate = "age gate" in desc_lower or "21+" in desc_lower
                # Escape Chromium Safe Browsing / Settings traps before key taps.
                try:
                    focus = (
                        self.farm.adb.shell(
                            "dumpsys window | grep mCurrentFocus",
                            serial=serial,
                        ).stdout
                        or ""
                    )
                    if (
                        "SettingsActivity" in focus
                        or "GoogleSettingsActivity" in focus
                        or "SafeBrowsing" in focus
                    ):
                        logger.warning(
                            "Browser settings trap on %s - backing out before tap (%s)",
                            serial,
                            step.description[:40],
                        )
                        for _ in range(3):
                            self.farm.adb.shell("input keyevent 4", serial=serial)
                            time.sleep(0.35)
                except Exception as exc:
                    logger.debug("settings-trap check soft-fail %s: %s", serial, exc)
                # Clear late DDG AI picker / Brave News / Firefox sheets before key taps.
                if is_age_gate or "start perfect dab" in desc_lower or "material" in desc_lower:
                    try:
                        pkg = (
                            sequence.preferred_browser
                            or (get_sequence_browser(phone).package if get_sequence_browser(phone) else "")
                        )
                        if pkg:
                            dismiss_blocking_browser_overlays(
                                self.farm.adb,
                                serial,
                                pkg,
                                dump_ui=dump_browser_ui,
                            )
                    except Exception as exc:
                        logger.debug("overlay dismiss soft-fail %s: %s", serial, exc)
                # open_url waits for gate paint; this tap is a safety retap + post-Yes settle.
                # Path3 ad steps are authored as "Tap ad (home slot 0)", not
                # "banner"/"mantis". Match both legacy and current descriptions.
                is_ad_tap = (
                    "tap ad" in desc_lower
                    or (
                        "ad" in desc_lower
                        and (
                            "banner" in desc_lower
                            or "mantis" in desc_lower
                            or "slot" in desc_lower
                            or "sponsored" in desc_lower
                        )
                    )
                )
                allow_ads = _farm_ads_allowed()
                is_path3_seq = is_path3_sequence_name(sequence.name or "")
                # Clicks only on Path3 when ads are explicitly allowed.
                # Path1/2 (and ads-off nights) never burn Mantis click budget.
                if is_ad_tap and (not is_path3_seq or not allow_ads):
                    inst = self._resolve_phone(phone)
                    phone_idx = _inst_phone_idx(inst) if inst else 0
                    logger.warning(
                        "Blocked ad-tap seq=%s path3=%s allow_ads=%s desc=%s",
                        sequence.name,
                        is_path3_seq,
                        allow_ads,
                        step.description,
                    )
                    try:
                        resume_tor_after_ads(self.farm.adb, serial, phone_idx)
                    except Exception as exc:
                        logger.warning("post-blocked-ad Tor restore soft-fail: %s", exc)
                    result["ok"] = True
                    result["ad_blocked_non_path3"] = True
                    result["ad_blocked_ads_off"] = not allow_ads
                    result["coords"] = (0, 0)
                    return result
                if is_ad_tap:
                    inst = self._resolve_phone(phone)
                    phone_idx = _inst_phone_idx(inst) if inst else 0
                    paused = pause_tor_for_ads(self.farm.adb, serial, phone_idx)
                    if (
                        isinstance(paused, dict)
                        and paused.get("ok") is False
                        and not paused.get("skipped")
                    ):
                        logger.warning(
                            "ad tap refused — guest has no loopback exit serial=%s",
                            serial,
                        )
                        result["ok"] = False
                        result["error"] = "ad tap refused — guest has no loopback exit"
                        return result
                    checkpoint = ad_checkpoint_from_description(step.description)
                x = resolve_coordinate(p["x"], hz.coordinate_tolerance)
                y = resolve_coordinate(p["y"], hz.coordinate_tolerance)
                x, y = self._scale(x, y, phone, sequence)
                # Coords were recorded in Chromium; Firefox/Brave reserve different
                # toolbar space, so map into the browser's live page rect.
                if not is_ad_tap:
                    remapped_y = remap_y(serial, y)
                    if remapped_y != y:
                        result["viewport_y"] = {"authored": y, "live": remapped_y}
                        y = remapped_y
                # Age gate: just tap the JSON coords — no dump, no verification.
                # The JSON has the correct Yes-button coords baked in.
                if is_age_gate:
                    result["age_gate_source"] = "json_coords"
                # Path3 only: human-style random tab + live creative every sequence.
                # Always engage — host SSP probes can disagree with phone CDP fills.
                # open_url below decides billable vs house after we see the real href.
                if is_ad_tap:
                    try:
                        inst = self._resolve_phone(phone)
                        phone_idx = _inst_phone_idx(inst) if inst else 0

                        def _after_nav_paint(
                            _tab: str, _zone: str, cp: str
                        ) -> None:
                            # Paint outcome must be visible in the farm log — a
                            # silent skip (e.g. unrecognized browser package or
                            # inject-proxy miss) is how empty ad zones passed as
                            # "OK" while the phone showed nothing.
                            def _log_paint(msg: str) -> None:
                                logger.info(
                                    "[%s] AD PAINT %s (zone=%s cp=%s)",
                                    phone,
                                    msg,
                                    _zone,
                                    cp,
                                )

                            paint = ensure_ads_visible_browser_hidden(
                                self.farm.adb,
                                serial,
                                phone_idx,
                                checkpoint=cp,
                                paint_creatives=True,
                                interactive=True,
                                resume_tor=False,
                                log_fn=_log_paint,
                            )
                            result["ad_paint"] = paint
                            if paint.get("mantis_patch_error") or paint.get(
                                "pause_error"
                            ):
                                logger.warning(
                                    "[%s] AD PAINT soft-fail: %s",
                                    phone,
                                    paint.get("mantis_patch_error")
                                    or paint.get("pause_error"),
                                )

                        def _cdp_targets() -> list:
                            return cdp_creative_tap_targets(
                                self.farm.adb, serial, phone_idx
                            )

                        live = human_path3_ad_engage(
                            self.farm.adb,
                            serial,
                            fallback_xy=(x, y),
                            scale_fn=lambda sx, sy: self._scale(
                                sx, sy, phone, sequence
                            ),
                            after_nav_paint=_after_nav_paint,
                            cdp_targets_fn=_cdp_targets,
                        )
                        checkpoint = str(live.get("checkpoint") or checkpoint)
                        x, y = int(live["x"]), int(live["y"])
                        result["ad_pick"] = live
                    except Exception as exc:
                        logger.warning("live ad pick soft-fail: %s - using sequence coords", exc)
                # Block Chrome omnibox / Google voice-search mic taps (top bar).
                if y < MIN_SAFE_TAP_Y and "interstitial" not in desc_lower and "chromium" not in desc_lower:
                    logger.warning(
                        "Blocked omnibox-zone tap y=%d (%s) - bumping to safe Y",
                        y,
                        step.description,
                    )
                    y = MIN_SAFE_TAP_Y + 40 + (abs(hash(step.description)) % 80)
                # Chromium FRE Skip: dismiss only if splash visible; otherwise no-op (no Help hits).
                is_chromium_skip = "chromium" in desc_lower and (
                    "skip" in desc_lower or "stay signed" in desc_lower
                )
                if is_chromium_skip:
                    fre_ok = dismiss_chromium_fre(self.farm.adb, serial)
                    logger.info(
                        "Chromium FRE dismiss via dump (%s) ok=%s",
                        step.description,
                        fre_ok,
                    )
                    # Already-past-splash returns True. A False means the sheet
                    # is still up. Counting that as ok sends the next taps at
                    # Stay signed out instead of the page.
                    result["ok"] = bool(fre_ok)
                    result["fre_dismiss"] = fre_ok
                    result["coords"] = (x, y)
                    if not result["ok"]:
                        result["error"] = "Chromium first-run sheet is still up"
                    return result
                # Start Perfect Dab: scroll-reveal + live bounds; verify timer; never double-tap.
                is_start_dab = "start perfect dab" in desc_lower or (
                    "start" in desc_lower and "timer" in desc_lower and "perfect" in desc_lower
                )
                if is_start_dab:
                    start_report = ensure_start_perfect_dab(
                        self.farm.adb,
                        serial,
                        fallback_xy=(x, y),
                    )
                    result["coords"] = start_report.get("coords") or (x, y)
                    result["start_dab"] = start_report
                    # Success = timer confirmed (already-running counts; do not require a tap).
                    result["ok"] = bool(start_report.get("timer_started"))
                    if not result["ok"]:
                        result["error"] = "Start Perfect Dab did not confirm timer"
                    return result
                # Web app: single tap only. Path1/2 (or ads-off): never land on a live ad card.
                if not is_ad_tap and (
                    not is_path3_sequence_name(sequence.name or "") or not _farm_ads_allowed()
                ):
                    try:
                        nx, ny, moved = nudge_tap_off_ads(
                            self.farm.adb, serial, int(x), int(y)
                        )
                        if moved:
                            result["ad_nudge"] = {"from": (x, y), "to": (nx, ny)}
                            x, y = nx, ny
                    except Exception as exc:
                        logger.debug("ad nudge soft-fail: %s", exc)
                skip_fg = should_skip_content_tap(self.farm.adb, serial)
                pkg = ""
                if skip_fg:
                    try:
                        br = get_sequence_browser(phone)
                        pkg = (
                            (sequence.preferred_browser or "").strip()
                            or (br.package if br else "")
                            or "org.chromium.chrome"
                        )
                    except Exception:
                        pkg = (sequence.preferred_browser or "").strip() or "org.chromium.chrome"
                if skip_fg and (is_ad_tap or is_age_gate):
                    # Lawnchair often steals FG mid-Path3; recover browser then recheck.
                    try:
                        was_fg = skip_fg
                        bring_browser_foreground_dabflow(self.farm.adb, serial, pkg)
                        time.sleep(0.35)
                        skip_fg = should_skip_content_tap(self.farm.adb, serial)
                        if not skip_fg:
                            logger.info(
                                "recovered FG for tap serial=%s pkg=%s was=%s desc=%s",
                                serial,
                                pkg,
                                was_fg,
                                step.description[:48],
                            )
                    except Exception as exc:
                        logger.warning(
                            "FG recover soft-fail serial=%s desc=%s: %s",
                            serial,
                            step.description[:40],
                            exc,
                        )
                if skip_fg:
                    # Aggressive recovery: force-stop the launcher, wait, recheck.
                    try:
                        if "lawnchair" in skip_fg or "launcher" in skip_fg:
                            self.farm.adb.shell(
                                f"am force-stop {skip_fg}", serial=serial
                            )
                            time.sleep(0.8)
                            bring_browser_foreground_dabflow(
                                self.farm.adb, serial, pkg
                            )
                            time.sleep(0.4)
                            skip_fg = should_skip_content_tap(
                                self.farm.adb, serial
                            )
                    except Exception:
                        pass
                if skip_fg:
                    logger.warning(
                        "skip tap on foreign FG (%s) serial=%s desc=%s",
                        skip_fg,
                        serial,
                        step.description[:48],
                    )
                    result["skipped_foreign_fg"] = skip_fg
                    result["coords"] = (x, y)
                    # The tap did not happen. Counting it ok continues the
                    # sequence on the wrong app.
                    result["ok"] = False
                    result["error"] = f"foreign_fg:{skip_fg}"
                    return result
                # Wake screen before every tap — screen may have timed out.
                try:
                    self.farm.adb.shell("input keyevent 224", serial=serial)
                    time.sleep(0.15)
                except Exception:
                    pass
                r = self.farm.adb.tap(x, y, serial=serial)
                # One soft retry on ADB flake (timeout/congestion) — do not burn the seq.
                if not r.ok:
                    time.sleep(0.55)
                    try:
                        self.farm.adb.shell("input keyevent 224", serial=serial)
                        time.sleep(0.15)
                    except Exception:
                        pass
                    r = self.farm.adb.tap(x, y, serial=serial)
                    result["adb_retry"] = True
                result["coords"] = (x, y)
                result["ok"] = r.ok
                if is_age_gate and r.ok:
                    # Just settle briefly — ad paint happens at the ad tap step.
                    time.sleep(AGE_GATE_POST_YES_SETTLE_S)
                if is_ad_tap and r.ok:
                    checkpoint = ad_checkpoint_from_description(step.description)
                    pick = result.get("ad_pick") if isinstance(result.get("ad_pick"), dict) else {}
                    if pick.get("checkpoint"):
                        checkpoint = str(pick.get("checkpoint"))
                    zone = str(pick.get("zone") or "")
                    raw_click = str(pick.get("click_url") or "")
                    # Host SSP tokens do not match the impression this phone
                    # viewed. Open only the click URL the phone itself fetched.
                    prefer_click = ""
                    if has_live_click_token(raw_click):
                        prefer_click = raw_click
                    else:
                        # vm0 is index 0. Skipping it left the first phone with
                        # no billed open when CDP had no href.
                        viewed_idx = int(phone_idx)
                        for _wait in range(8):
                            prefer_click = phone_viewed_click_url(viewed_idx, zone)
                            if prefer_click:
                                break
                            time.sleep(0.35)
                    prefer_ok = bool(prefer_click)
                    proxy = ""
                    try:
                        proxy = (
                            self.farm.adb.shell(
                                "settings get global http_proxy", serial=serial
                            ).stdout
                            or ""
                        ).strip()
                    except Exception:
                        proxy = ""
                    logger.info(
                        "Path3 click serial=%s zone=%s source=%s live_token=%s proxy=%s",
                        serial,
                        zone or "*",
                        "phone_page" if prefer_ok else "none",
                        1 if prefer_ok else 0,
                        proxy or "missing",
                    )
                    if prefer_ok and prefer_click.startswith("http") and not guest_proxy_healthy(proxy):
                        try:
                            proxy = str(
                                pin_guest_proxy(self.farm.adb, serial, int(phone_idx), attempts=1) or ""
                            ).strip()
                        except Exception as exc:
                            logger.warning("Path3 exit pin failed serial=%s: %s", serial, exc)
                            proxy = ""
                    fb = False
                    if (
                        prefer_ok
                        and prefer_click.startswith("http")
                        and not guest_proxy_healthy(proxy)
                    ):
                        logger.error(
                            "Path3 click refused — guest proxy %r is not a loopback exit serial=%s",
                            proxy or "missing",
                            serial,
                        )
                        result["error"] = "click refused — guest has no loopback exit"
                        result["ad_fallback"] = False
                    elif prefer_ok and prefer_click.startswith("http"):
                        seq_browser = get_sequence_browser(phone)
                        if seq_browser is None:
                            try:
                                pkg = browser_package_for_serial(serial)
                                if pkg:
                                    seq_browser = browser_info_for_package(pkg)
                            except Exception:
                                seq_browser = None

                        def _open_click_url(s: str, u: str) -> bool:
                            return adb_open_url(
                                self.farm.adb,
                                s,
                                u,
                                browser=seq_browser,
                            )

                        # Jul 30: open the SSP click_url. Painted slot taps do not bill.
                        fb = maybe_fallback_ad_open_url(
                            self.farm.adb,
                            serial,
                            checkpoint,
                            open_url_fn=_open_click_url,
                            force_click_url=True,
                            prefer_click_url=prefer_click,
                            log_fn=lambda m: logger.info(m),
                        )
                        if not fb:
                            logger.error(
                                "Path3 click_url OPEN FAILED serial=%s checkpoint=%s "
                                "prefer=%s - Mantis clicks will stay flat",
                                serial,
                                checkpoint,
                                prefer_click[:80],
                            )
                    else:
                        logger.warning(
                            "Path3 skip open_url - no click_url serial=%s",
                            serial,
                        )
                    result["ad_fallback"] = fb
                    result["ad_fallback_forced"] = True
                    # After a billable open: slowly scroll the offer. Skip on
                    # house-only fail — saves ~15s and we already refund quota.
                    if fb:
                        try:
                            result["ad_landing_scroll"] = human_scroll_ad_landing(
                                self.farm.adb, serial
                            )
                        except Exception as exc:
                            logger.warning("ad-landing human scroll soft-fail: %s", exc)
                    # After Path3 engage (or failed empty tap), get chrome out of the way again.
                    try:
                        hide_browser_chrome(self.farm.adb, serial)
                    except Exception:
                        pass
                elif is_ad_tap:
                    logger.warning(
                        "Path3 ad tap failed — skip open_url serial=%s coords=(%s,%s)",
                        serial,
                        x,
                        y,
                    )
                    try:
                        hide_browser_chrome(self.farm.adb, serial)
                    except Exception:
                        pass
                if is_ad_tap:
                    inst = self._resolve_phone(phone)
                    phone_idx = _inst_phone_idx(inst) if inst else 0
                    try:
                        resume_tor_after_ads(self.farm.adb, serial, phone_idx)
                    except Exception as exc:
                        logger.warning("post-ad-tap Tor restore soft-fail: %s", exc)
                    try:
                        from automation.browse_proxy import pin_guest_proxy

                        pin_guest_proxy(self.farm.adb, serial, int(phone_idx))
                    except Exception as exc:
                        logger.warning("post-ad-tap proxy pin soft-fail: %s", exc)
                if result.get("ok") and step_wants_session_notes_dismiss(p):
                    # The next tap is the tab. A sheet that stays up eats that tap.
                    # A dump that finds no Skip returns immediately. A dump that
                    # sees the sheet and cannot clear it stops this sequence.
                    if not dismiss_session_notes_verified(serial):
                        logger.warning("popup dismiss did not land serial=%s", serial)
                        result["ok"] = False
                        result["error"] = "session notes sheet is still up"
            elif action == StepAction.WAIT:
                seconds = resolve_seconds(p.get("seconds", 1.0), hz.timing_variation)
                desc_lower = step.description.lower()
                # Existing JSON used 0.05-0.12s after age gate - too short for home paint.
                if "home screen" in desc_lower or "after ad re-entry" in desc_lower:
                    if seconds < HOME_SCREEN_WAIT_MIN_S:
                        seconds = random.uniform(
                            HOME_SCREEN_WAIT_MIN_S, HOME_SCREEN_WAIT_MAX_S
                        )
                # Mantis viewability (cloud docs): premium ads load at TOP after
                # mantis.push refresh on every tab switch. Floor tab-open / settle
                # waits to the impression minimum only (env-tunable, default
                # 1.0-1.5s) — not the old 3-5s, which doubled sequence cycles.
                tab_dwell = (
                    "settle on" in desc_lower
                    or "open tab" in desc_lower
                    or "after tab" in desc_lower
                    or "tab switch" in desc_lower
                    or desc_lower.startswith("land")
                )
                evcpm_push = (os.environ.get("PHARMFLOW_EVCPM_PUSH") or "").strip().lower() in (
                    "1",
                    "true",
                    "yes",
                    "on",
                )
                dwell_lo = _env_float(
                    "PHARMFLOW_TAB_DWELL_MIN_S", 1.5 if evcpm_push else 1.0
                )
                dwell_hi = _env_float(
                    "PHARMFLOW_TAB_DWELL_MAX_S", dwell_lo + (0.5 if evcpm_push else 0.5)
                )
                dwell_hi = max(dwell_hi, dwell_lo + 0.2)
                if tab_dwell and seconds < dwell_lo:
                    seconds = random.uniform(dwell_lo, dwell_hi)
                    result["tab_dwell_floor"] = True
                # After scroll-to-bottom: short settle so bottom zones register
                # viewed (impression minimum, env-tunable, default 0.5-0.9s).
                scroll_settle = (
                    "scroll" in desc_lower
                    and ("bottom" in desc_lower or "settle" in desc_lower or "end" in desc_lower)
                )
                scroll_lo = _env_float(
                    "PHARMFLOW_SCROLL_SETTLE_MIN_S", 0.8 if evcpm_push else 0.5
                )
                scroll_hi = _env_float(
                    "PHARMFLOW_SCROLL_SETTLE_MAX_S", scroll_lo + (0.4 if evcpm_push else 0.4)
                )
                scroll_hi = max(scroll_hi, scroll_lo + 0.2)
                if scroll_settle and seconds < scroll_lo:
                    seconds = random.uniform(scroll_lo, scroll_hi)
                    result["scroll_dwell_floor"] = True
                time.sleep(seconds)
                result["ok"] = True
                result["slept"] = seconds
                if step_wants_session_notes_gone(p) and not wait_session_notes_gone(
                    serial, timeout_sec=8.0
                ):
                    logger.warning("session notes still up serial=%s", serial)
                    result["ok"] = False
                    result["error"] = "session notes sheet is still up"
                if "home screen" in desc_lower or "after ad re-entry" in desc_lower:
                    try:
                        hide_browser_chrome(self.farm.adb, serial)
                    except Exception:
                        pass
            elif action == StepAction.SWIPE:
                p = normalize_swipe_params(p)
                x1 = resolve_coordinate(p.get("x1", p.get("x_start", 0)), hz.coordinate_tolerance)
                y1 = resolve_coordinate(p.get("y1", p.get("y_start", 0)), hz.coordinate_tolerance)
                x2 = resolve_coordinate(p.get("x2", p.get("x_end", 0)), hz.coordinate_tolerance)
                y2 = resolve_coordinate(p.get("y2", p.get("y_end", 0)), hz.coordinate_tolerance)
                x1, y1 = self._scale(x1, y1, phone, sequence)
                x2, y2 = self._scale(x2, y2, phone, sequence)
                y1 = remap_y(serial, y1)
                y2 = remap_y(serial, y2)
                seed = hash(sequence.name) & 0xFFFFFFFF
                x1, y1, x2, y2 = enforce_scroll_coords(x1, y1, x2, y2, seed=seed)
                duration = resolve_duration_ms(p.get("duration_ms", p.get("duration")), hz.scroll_duration_ms)
                r = self.farm.adb.swipe(x1, y1, x2, y2, duration, serial=serial)
                if not r.ok:
                    time.sleep(0.55)
                    r = self.farm.adb.swipe(x1, y1, x2, y2, duration, serial=serial)
                    result["adb_retry"] = True
                result["coords"] = (x1, y1, x2, y2)
                result["ok"] = r.ok
                result["duration_ms"] = duration
            elif action == StepAction.OPEN_URL:
                result["ok"] = browse_url(self.farm, phone, p["url"])
                result["url"] = p["url"]
                if result["ok"]:
                    url_l = str(p.get("url", "")).lower()
                    dabflow = "getdabflow" in url_l
                    # DabFlow: open_url already taps age-gate Yes - no UI dumps here
                    # (dismiss_native_alert / omnibox dump were causing 1-5s stalls).
                    if not dabflow:
                        try:
                            dismiss_native_alert(self.farm.adb, serial)
                        except Exception:
                            pass
                        try:
                            defocus_chromium_omnibox(self.farm.adb, serial)
                        except Exception:
                            pass
                if not result["ok"]:
                    result["error"] = "open_url failed (browser/fingerprint/device)"
            elif action == StepAction.LAUNCH_APP:
                pkg = str(p.get("package", "")).strip()
                # Chromium-only: never honor Brave/Firefox/DDG packages baked into
                # older stem JSONs — launch the chosen Chromium instead.
                browsers_raw = (
                    os.environ.get("PHARMFLOW_FARM_BROWSERS") or ""
                ).strip().lower()
                browser_tags = {p.strip() for p in browsers_raw.split(",") if p.strip()}
                chromium_only = (
                    os.environ.get("PHARMFLOW_FARM_CHROMIUM_ONLY") or ""
                ).strip().lower() in ("1", "true", "yes", "on")
                if chromium_only or browser_tags == {"chromium"}:
                    chosen = get_sequence_browser(phone)
                    remap = (
                        (chosen.package if chosen is not None else "") or BROWSER_CHROMIUM
                    ).strip()
                    if remap and pkg != remap:
                        logger.info(
                            "[%s] launch_app remap %s -> %s (chromium-only)",
                            phone,
                            pkg or "(empty)",
                            remap,
                        )
                        pkg = remap
                ok = launch_app(self.farm.adb, serial, pkg)
                result["ok"] = ok
                result["package"] = pkg
                if not ok:
                    result["error"] = f"launch_app failed for {pkg or '(empty package)'}"
            elif action == StepAction.ROTATE_IDENTITY:
                # Runner already did full isolation (IP + fingerprint + geo + IMEI
                # + inject) before this sequence. The authored rotate_identity step
                # is present in every sequence and would re-do all of it (~60-100s).
                # Skip it: identity was just rotated and IP is already unique.
                if self._iso_done and self._iso_phone == phone:
                    result["ok"] = True
                    result["skipped"] = True
                    result["warning"] = "identity already rotated by runner isolation"
                    # Resolve phone_idx HERE — it is referenced below for the
                    # belt-and-suspenders inject restore, and was previously
                    # unbound in this branch (UnboundLocalError soft-fail left
                    # Chromium unpinned → clicks/impressions lost every sequence).
                    _skip_inst = self._resolve_phone(phone)
                    if _skip_inst is None:
                        _skip_inst = getattr(self.farm, "instances", {}).get(phone)
                    phone_idx = _inst_phone_idx(_skip_inst) if _skip_inst is not None else 0
                    by_phone = getattr(self.farm, "_last_exit_ip_rotate_by_phone", None)
                    ip_info = by_phone.get(phone) if isinstance(by_phone, dict) else None
                    if ip_info is None:
                        ip_info = getattr(self.farm, "_last_exit_ip_rotate", None)
                    if ip_info is not None:
                        result["exit_ip"] = getattr(ip_info, "after", "")
                        result["ip_before"] = getattr(ip_info, "before", "")
                        result["ip_changed"] = bool(getattr(ip_info, "changed", False))
                        result["ip_retries"] = int(getattr(ip_info, "retries", 0) or 0)
                        logger.info("[%s] rotate_identity SKIPPED (runner isolation) %s", phone, ip_info.log_line())
                    else:
                        logger.info("[%s] rotate_identity SKIPPED (runner isolation)", phone)
                    # Belt-and-suspenders: never leave Chromium on :0 after rotate.
                    try:
                        chosen = get_sequence_browser(phone)
                        pkg = (
                            getattr(chosen, "package", None)
                            or browser_package_for_serial(serial)
                            or ""
                        )
                        pinned = restore_inject_after_identity(
                            self.farm.adb,
                            serial,
                            int(phone_idx),
                            browser_package=pkg or None,
                        )
                        result["http_proxy"] = pinned
                    except Exception as pin_exc:
                        logger.warning(
                            "[%s] post-rotate inject restore soft-fail: %s",
                            phone,
                            pin_exc,
                        )
                else:
                    prof = None
                    try:
                        prof = self.farm.rotate_identity(phone)
                    except Exception as exc:
                        result["ok"] = False
                        result["error"] = str(exc)
                        result["warning"] = str(exc)
                    else:
                        # Cold boot may change ADB serial (ARM 10.0.2.x) - wait and refresh.
                        self.farm.refresh_serials()
                        inst = self._resolve_phone(phone)
                        if inst:
                            serial = inst.adb_serial
                            phone_idx = _inst_phone_idx(inst)
                            online = self.farm.adb.wait_for_device(serial, timeout=90.0)
                            result["ok"] = online
                            if not online:
                                result["error"] = f"device offline after rotate_identity ({serial})"
                            else:
                                # Belt-and-suspenders: never leave Chromium on :0 after rotate.
                                try:
                                    chosen = get_sequence_browser(phone)
                                    pkg = (
                                        getattr(chosen, "package", None)
                                        or browser_package_for_serial(serial)
                                        or ""
                                    )
                                    pinned = restore_inject_after_identity(
                                        self.farm.adb,
                                        serial,
                                        int(phone_idx),
                                        browser_package=pkg or None,
                                    )
                                    result["http_proxy"] = pinned
                                except Exception as pin_exc:
                                    logger.warning(
                                        "[%s] post-rotate inject restore soft-fail: %s",
                                        phone,
                                        pin_exc,
                                    )
                        else:
                            result["ok"] = False
                            result["error"] = "phone missing after rotate_identity"
                    if prof is not None:
                        result["imei"] = getattr(prof, "imei", "")
                    by_phone = getattr(self.farm, "_last_exit_ip_rotate_by_phone", None)
                    ip_info = by_phone.get(phone) if isinstance(by_phone, dict) else None
                    if ip_info is None:
                        ip_info = getattr(self.farm, "_last_exit_ip_rotate", None)
                    if ip_info is not None:
                        result["exit_ip"] = getattr(ip_info, "after", "")
                        result["ip_before"] = getattr(ip_info, "before", "")
                        result["ip_changed"] = bool(getattr(ip_info, "changed", False))
                        result["ip_retries"] = int(getattr(ip_info, "retries", 0) or 0)
                        logger.info("[%s] %s", phone, ip_info.log_line())
            elif action == StepAction.CLEAR_COOKIES:
                chosen = get_sequence_browser(phone)
                pkg = str(
                    p.get("package")
                    or (chosen.package if chosen else "")
                    or BROWSER_CHROMIUM
                ).strip()
                packages = set(self.farm.adb.pm_list_packages(serial=serial))
                if pkg not in packages and BROWSER_CHROMIUM not in packages:
                    result["ok"] = False
                    result["package"] = pkg
                    result["error"] = "browser not installed — cookies were not cleared"
                    logger.warning("clear_cookies did not land on %s: %s not installed", serial, pkg)
                else:
                    use_pkg = pkg if pkg in packages else BROWSER_CHROMIUM
                    ok = clear_browser_package(self.farm.adb, serial, use_pkg)
                    if not ok:
                        time.sleep(0.4)
                        ok = clear_browser_package(self.farm.adb, serial, use_pkg)
                        result["adb_retry"] = True
                    result["ok"] = bool(ok)
                    result["package"] = use_pkg
                    if not ok:
                        result["error"] = "browser cookies were not cleared"
            elif action == StepAction.ENSURE_FINGERPRINT:
                if sequence.requires_fingerprint and not is_skip_fingerprint():
                    header_report = verify_before_browse(self.farm, phone)
                    result["ok"] = getattr(header_report, "passed", False)
                    result["checks"] = header_report.to_dict() if hasattr(header_report, "to_dict") else {}
                    if not result["ok"]:
                        failures = list(
                            getattr(header_report, "failures", []) or ["browser headers not verified"]
                        )
                        # Firefox/DDG do not use chrome-command-line — do not kill the
                        # sequence on a Chromium-only check (was collapsing OK rate to ~1/6).
                        chosen = get_sequence_browser(phone)
                        pkg = (
                            getattr(chosen, "package", None)
                            or sequence.preferred_browser
                            or ""
                        ).lower()
                        non_chromium = any(
                            x in pkg for x in ("firefox", "duckduckgo", "org.mozilla")
                        )
                        chrome_flag_only = failures and all(
                            "chrome-command-line" in f or "AutomationControlled" in f
                            for f in failures
                        )
                        if non_chromium and chrome_flag_only:
                            result["ok"] = True
                            result["warning"] = (
                                "chrome-command-line N/A for non-chromium browser; continuing"
                            )
                        elif chrome_flag_only and is_path3_sequence_name(
                            getattr(sequence, "name", "") or ""
                        ):
                            # Path3 clicks were dying on stale chrome-command-line
                            # model string after scramble — keep sequence alive so
                            # inject/MITM + tap path can still earn.
                            result["ok"] = True
                            result["warning"] = (
                                "chrome-command-line soft-fail Path3; continuing: "
                                + "; ".join(failures)
                            )
                            logger.warning(
                                "Path3 ENSURE_FINGERPRINT soft-fail %s: %s",
                                phone,
                                failures,
                            )
                        else:
                            result["error"] = "; ".join(failures)
                else:
                    scramble_for_sequence(self.farm, phone)
                    result["ok"] = True
                    result["skipped"] = is_skip_fingerprint()
            elif action == StepAction.CLOSE_APP:
                requested = str(p.get("package") or "").strip()
                packages = set(self.farm.adb.pm_list_packages(serial=serial))
                pkg = requested if requested in packages else ""
                if not pkg and not requested and BROWSER_CHROMIUM in packages:
                    pkg = BROWSER_CHROMIUM
                if not pkg:
                    missing = requested or BROWSER_CHROMIUM
                    result["ok"] = False
                    result["package"] = missing
                    result["error"] = "browser not installed — app was not closed"
                    logger.warning("close_app did not land on %s: %s not installed", serial, missing)
                else:
                    r = self.farm.adb.shell(f"am force-stop {pkg}", serial=serial)
                    result["ok"] = bool(r.ok)
                    result["package"] = pkg
                    if not result["ok"]:
                        result["error"] = "app was not closed"
            elif action == StepAction.BACK:
                r = self.farm.adb.keyevent(ANDROID_KEY_BACK, serial=serial)
                result["ok"] = r.ok
            elif action == StepAction.KEY:
                code = _key_code(p)
                if code is None:
                    result["ok"] = False
                    result["error"] = "key step has no usable key"
                else:
                    r = self.farm.adb.keyevent(code, serial=serial)
                    result["ok"] = r.ok
                    if not result["ok"]:
                        result["error"] = "key event did not land"
            elif action == StepAction.SHELL:
                r = self.farm.adb.shell(p["command"], serial=serial)
                result["ok"] = r.ok
                result["output"] = r.stdout
            elif action == StepAction.KEYEVENT:
                code = _key_code(p)
                if code is None:
                    result["ok"] = False
                    result["error"] = "keyevent step has no usable key"
                else:
                    r = self.farm.adb.keyevent(code, serial=serial)
                    result["ok"] = r.ok
                    if not result["ok"]:
                        result["error"] = "key event did not land"
            elif action == StepAction.TYPE_TEXT:
                raw_text = str(p.get("text") or "")
                if not raw_text:
                    result["ok"] = False
                    result["error"] = "type_text has no text"
                else:
                    quoted = urllib.parse.quote(raw_text, safe="").replace("%20", "%s")
                    r = self.farm.adb.shell(f"input text {quoted}", serial=serial)
                    result["ok"] = bool(r.ok)
                    if not result["ok"]:
                        result["error"] = "type_text did not land"
            elif action == StepAction.FULL_RESET:
                _ri = self._resolve_phone(phone) or getattr(self.farm, "instances", {}).get(phone)
                phone_idx = _inst_phone_idx(_ri) if _ri is not None else 0
                reset = tor_manager.full_identity_reset(serial, phone_idx)
                result["reset"] = reset if isinstance(reset, dict) else {}
                # A planned port is not a pin. MAC/IMEI stay best-effort (root).
                result["ok"] = bool(result["reset"].get("http_proxy_applied"))
                if not result["ok"]:
                    result["error"] = "identity reset did not pin a loopback exit"
                warnings: list[str] = []
                if result["reset"].get("tor_circuit_rotated") is False:
                    warnings.append("tor_circuit_rotated=false")
                if not result["reset"].get("android_id_applied"):
                    warnings.append("android_id did not stick")
                if warnings:
                    result["warning"] = "; ".join(warnings)
            else:
                result["ok"] = False
                result["error"] = f"Unknown action: {action}"
        except Exception as exc:
            logger.exception("Step failed")
            result["ok"] = False
            result["error"] = str(exc)
        return result

    def _scale(self, x: int, y: int, phone: str, sequence: Sequence) -> tuple[int, int]:
        return self.farm.scale_coordinates(x, y, phone, sequence.author_width, sequence.author_height)

    @staticmethod
    def load_sequences(directory: Path, *, recursive: bool = True) -> list[Sequence]:
        sequences: list[Sequence] = []
        if not directory.is_dir():
            return sequences
        pattern = "**/*.json" if recursive else "*.json"
        for f in sorted(directory.glob(pattern)):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                if "steps" in data:
                    sequences.append(Sequence.from_json(f))
            except (json.JSONDecodeError, KeyError, ValueError) as exc:
                logger.warning("Skipping %s: %s", f, exc)
        return sequences
