"""Browser session identity — per-sequence retail UA/model + android_id rotation."""

from __future__ import annotations

import logging
import os
import random
import re
import tempfile
from dataclasses import dataclass, field
from typing import Any

from automation.adb_wrapper import AdbWrapper
from automation.browser_privacy import append_privacy_flags
from automation.config import BROWSER_CHROMIUM

logger = logging.getLogger(__name__)

CHROME_FLAGS_PATH = "/data/local/tmp/chrome-command-line"
CHROME_FLAGS_PATH_ROOT = "/data/local/chrome-command-line"
WEBVIEW_FLAGS_PATH = "/data/local/tmp/webview-command-line"
WEBVIEW_FLAGS_PATH_ROOT = "/data/local/webview-command-line"
# Opera Chromium fork reads this path (see OperaChromiumDriver android docs).
OPERA_FLAGS_PATH = "/data/local/tmp/opera-browser-command-line"
OPERA_FLAGS_PATH_ROOT = "/data/local/opera-browser-command-line"
CHROME_FLAGS_PUSH_PATHS = (CHROME_FLAGS_PATH, CHROME_FLAGS_PATH_ROOT)
CHROME_PREFS_PATH = (
    f"/data/data/{BROWSER_CHROMIUM}/shared_prefs/{BROWSER_CHROMIUM}_preferences.xml"
)
# CachedFlag also lives in SafeModeValues — Chromium can keep preferences=false
# while SafeMode=true (or vice versa). Both must be true or flags/CDP stay dead.
CHROME_FLAG_PREFS_PATHS = (
    CHROME_PREFS_PATH,
    f"/data/data/{BROWSER_CHROMIUM}/shared_prefs/"
    f"{BROWSER_CHROMIUM}.browser.flags.SafeModeValues.xml",
)

_VERSION_NAME_RE = re.compile(r"versionName=([0-9.]+)")
_FORBIDDEN_MODEL_SUBSTR = ("mumu", "generic", "sdk_gphone", "android_x86", "vbox")


@dataclass(frozen=True)
class DeviceIdentity:
    """Retail identity read from the phone via getprop — not hardcoded."""

    brand: str
    manufacturer: str
    model: str
    android_release: str
    build_id: str
    hardware: str = ""

    @property
    def key(self) -> str:
        safe = re.sub(r"[^a-zA-Z0-9]+", "_", self.model).strip("_").lower()
        return safe or "device"

    def is_usable(self) -> bool:
        if not self.model.strip() or not self.brand.strip():
            return False
        low = self.model.lower()
        return not any(b in low for b in _FORBIDDEN_MODEL_SUBSTR)


@dataclass(frozen=True)
class BrowserSessionProfile:
    key: str
    brand: str
    model: str
    user_agent: str
    android_id: str = ""
    source: str = "getprop"
    manufacturer: str = ""
    android_release: str = "13"
    build_id: str = "UNKNOWN"
    chrome_version: str = "120.0.6099.144"

    @classmethod
    def from_device(
        cls,
        identity: DeviceIdentity,
        *,
        chrome_version: str,
        android_id: str = "",
    ) -> BrowserSessionProfile:
        aid = android_id or _random_android_id()
        ua = build_mobile_user_agent(identity, chrome_version)
        return cls(
            key=f"{identity.key}_{aid[:8]}",
            brand=identity.brand,
            model=identity.model,
            user_agent=ua,
            android_id=aid,
            source="getprop",
            manufacturer=identity.manufacturer or identity.brand,
            android_release=identity.android_release or "13",
            build_id=identity.build_id or "UNKNOWN",
            chrome_version=chrome_version,
        )

    def user_agent_metadata(self) -> dict[str, Any]:
        """Chromium Client Hints payload for Emulation.setUserAgentOverride.

        Without this, Sec-CH-UA-Model stays stuck on MuMu PhoneProp/getprop even
        when --user-agent rotates — Cloudflare then sees ~N static devices.
        """
        ver = (self.chrome_version or "120.0.6099.144").strip()
        major = ver.split(".", 1)[0] or "120"
        brands = [
            {"brand": "Chromium", "version": major},
            {"brand": "Not=A?Brand", "version": "24"},
        ]
        full = [
            {"brand": "Chromium", "version": ver},
            {"brand": "Not=A?Brand", "version": "10.0.0.0"},
        ]
        release = (self.android_release or "13").strip() or "13"
        return {
            "brands": brands,
            "fullVersionList": full,
            "platform": "Android",
            "platformVersion": f"{release}.0.0",
            "architecture": "",
            "model": self.model,
            "mobile": True,
            "bitness": "",
            "wow64": False,
        }


@dataclass
class BrowserHeaderReport:
    serial: str
    passed: bool
    profile_key: str
    expected_model: str
    chrome_flags_ok: bool
    user_agent_in_flags: str = ""
    failures: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "serial": self.serial,
            "passed": self.passed,
            "profile_key": self.profile_key,
            "expected_model": self.expected_model,
            "chrome_flags_ok": self.chrome_flags_ok,
            "user_agent_in_flags": self.user_agent_in_flags,
            "failures": self.failures,
        }


def _random_android_id() -> str:
    return os.urandom(8).hex()


def _clean_prop(value: str) -> str:
    return (value or "").strip()


# Last scrambled model per serial — next seq must pick a different retail model.
_last_model_by_serial: dict[str, str] = {}
_last_android_id_by_serial: dict[str, str] = {}


def _pick_retail_identity(*, avoid_model: str = "") -> DeviceIdentity:
    """Pick a retail brand/model for this sequence (not sticky getprop)."""
    from automation.mumu_fingerprint import RETAIL_PROFILES

    pool = [p for p in RETAIL_PROFILES if p.get("model", "") != avoid_model] or list(RETAIL_PROFILES)
    base = random.choice(pool)
    # Prefer a build id from the fingerprint when present.
    build_id = "UNKNOWN"
    fp = (base.get("fingerprint") or "").strip()
    if fp and "/" in fp:
        build_id = _build_id_from_fingerprint(fp)
    release = "13"
    m = re.search(r":(\d+)/", fp)
    if m:
        release = m.group(1)
    return DeviceIdentity(
        brand=_clean_prop(base.get("brand", "")),
        manufacturer=_clean_prop(base.get("manufacturer", "")),
        model=_clean_prop(base.get("model", "")),
        android_release=release,
        build_id=build_id or "UNKNOWN",
        hardware=_clean_prop(base.get("hardware", "")),
    )


def profile_from_retail_pool(
    adb: AdbWrapper,
    serial: str,
    *,
    android_id: str = "",
    avoid_model: str = "",
) -> BrowserSessionProfile:
    """New session identity from the retail pool — model/UA change every scramble."""
    identity = _pick_retail_identity(avoid_model=avoid_model)
    chrome = read_chromium_version(adb, serial)
    aid = android_id or _random_android_id()
    ua = build_mobile_user_agent(identity, chrome)
    return BrowserSessionProfile(
        key=f"{identity.key}_{aid[:8]}",
        brand=identity.brand,
        model=identity.model,
        user_agent=ua,
        android_id=aid,
        source="retail_pool",
        manufacturer=identity.manufacturer or identity.brand,
        android_release=identity.android_release or "13",
        build_id=identity.build_id or "UNKNOWN",
        chrome_version=chrome,
    )


def read_secure_android_id(adb: AdbWrapper, serial: str) -> str:
    out = adb.shell("settings get secure android_id", serial=serial)
    return _clean_prop(getattr(out, "stdout", "") or "")


def _build_id_from_fingerprint(fp: str) -> str:
    """Extract build id from AOSP fingerprint ``brand/product/device:rel/id/...``."""
    parts = (fp or "").split("/")
    # google/panther/panther:14/AP2A.240805.005/12025142:user/release-keys
    # parts[3] is the build id — parts[1] is the product name (wrong).
    if len(parts) > 3:
        return parts[3].split(":")[0] or "UNKNOWN"
    if len(parts) >= 3 and ":" in parts[2]:
        return parts[2].split(":")[-1] or "UNKNOWN"
    return "UNKNOWN"


def read_device_identity(adb: AdbWrapper, serial: str) -> DeviceIdentity:
    """Read brand/model/build from the phone — each MuMu VM may differ."""
    build_id = _clean_prop(adb.getprop("ro.build.id", serial=serial))
    if not build_id:
        fp = _clean_prop(adb.getprop("ro.build.fingerprint", serial=serial))
        if fp and "/" in fp:
            build_id = _build_id_from_fingerprint(fp)
    return DeviceIdentity(
        brand=_clean_prop(adb.getprop("ro.product.brand", serial=serial)),
        manufacturer=_clean_prop(adb.getprop("ro.product.manufacturer", serial=serial)),
        model=_clean_prop(adb.getprop("ro.product.model", serial=serial)),
        android_release=_clean_prop(adb.getprop("ro.build.version.release", serial=serial)) or "13",
        build_id=build_id or "UNKNOWN",
        hardware=_clean_prop(adb.getprop("ro.hardware", serial=serial)),
    )


def read_chromium_version(adb: AdbWrapper, serial: str) -> str:
    """Read installed Chromium/Chrome version from the device package manager."""
    override = os.environ.get("PHARMFLOW_CHROME_VERSION", "").strip()
    if override:
        return override
    for pkg in (BROWSER_CHROMIUM, "com.android.chrome"):
        dump = adb.shell(f"dumpsys package {pkg} | grep versionName", serial=serial)
        text = dump.stdout or ""
        m = _VERSION_NAME_RE.search(text)
        if m:
            return m.group(1)
    return "120.0.6099.144"


def build_mobile_user_agent(identity: DeviceIdentity, chrome_version: str) -> str:
    model = identity.model
    return (
        f"Mozilla/5.0 (Linux; Android {identity.android_release}; {model} "
        f"Build/{identity.build_id}; wv) AppleWebKit/537.36 (KHTML, like Gecko) "
        f"Version/4.0 Chrome/{chrome_version} Mobile Safari/537.36"
    )


def profile_from_device(adb: AdbWrapper, serial: str, *, android_id: str = "") -> BrowserSessionProfile:
    identity = read_device_identity(adb, serial)
    if not identity.is_usable():
        logger.warning(
            "Device identity looks generic on %s (model=%r brand=%r) — using live getprop anyway",
            serial,
            identity.model,
            identity.brand,
        )
    chrome = read_chromium_version(adb, serial)
    return BrowserSessionProfile.from_device(identity, chrome_version=chrome, android_id=android_id)


def build_chromium_command_line(profile: BrowserSessionProfile, *, phone_index: int = 0) -> str:
    from automation.dabflow_mantis_client_patch import DEVICE_CDP_PORT, cdp_debug_flag

    ua = profile.user_agent
    # Device always listens on 9222; host forwards 9222+phone_index → device 9222.
    _ = phone_index
    # --remote-allow-origins=* required for CDP on Chromium 111+ (prior EXE protocol)
    base = (
        "chrome "
        "--enable-features=AllowChromeCommandLineInNonRootBuilds "
        "--disable-blink-features=AutomationControlled "
        f'--user-agent="{ua}" '
        f"{cdp_debug_flag(DEVICE_CDP_PORT)} "
        "--remote-allow-origins=* "
        "--disable-first-run-experience "
        "--no-default-browser-check --no-first-run "
        "--disable-fre --disable-sync-by-default "
        "--disable-restore-session-state "
        "--disable-session-crashed-bubble"
    )
    # MuMu RO /system often cannot persist MITM CA into Zygote trust; allow Chromium
    # to accept inject MITM certs when Mantis MITM is armed (still needs system CA when possible).
    if (os.environ.get('PHARMFLOW_MANTIS_INJECT_MITM') or '1').strip().lower() not in ('0','false','no','off'):
        if '--ignore-certificate-errors' not in base:
            base += ' --ignore-certificate-errors'
    # Telemetry/crash/sync hardening (see automation.browser_privacy limitations).
    return append_privacy_flags(base)


def _force_command_line_flag_in_prefs_xml(body: str, marker: str) -> str | None:
    """Return updated prefs XML with marker=true, or None if body is unusable."""
    if not body.strip():
        return None
    true_snip = f'<boolean name="{marker}" value="true" />'
    if f'{marker}" value="true"' in body and f'{marker}" value="false"' not in body:
        return body
    if marker in body:
        updated = body.replace(
            f'<boolean name="{marker}" value="false" />',
            true_snip,
        )
        # Any leftover false attribute variants
        updated = updated.replace(
            f'{marker}" value="false"',
            f'{marker}" value="true"',
        )
        return updated
    if "</map>" in body:
        return body.replace("</map>", f"    {true_snip}\n</map>")
    return None


def ensure_command_line_on_non_rooted(adb: AdbWrapper, serial: str) -> bool:
    """Flip Chrome.Flags.CachedFlag.CommandLineOnNonRooted so MuMu (user build) reads flags.

    Without this, /data/local/tmp/chrome-command-line is ignored → no CDP → Mantis
    zones never refresh → empty ad slots while the Chromium chrome stays visible.

    Writes via adb push (never echo-base64 on the shell cmdline — large prefs hit
    WinError 206 filename/command too long). Updates *both* preferences.xml and
    SafeModeValues.xml — live MuMu often had preferences=false while SafeMode=true,
    which left --remote-debugging-port dead (no listener on 9222).
    """
    marker = "Chrome.Flags.CachedFlag.CommandLineOnNonRooted"
    any_ok = False
    try:
        owner = adb.shell(f"stat -c '%u:%g' /data/data/{BROWSER_CHROMIUM}", serial=serial)
        uid_gid = (owner.stdout or "").strip() or "shell:shell"
        for prefs_path in CHROME_FLAG_PREFS_PATHS:
            local_path = ""
            try:
                cat = adb.shell(f"cat {prefs_path}", serial=serial)
                body = cat.stdout or ""
                if not body.strip():
                    # File missing — seed a minimal map so CachedFlag sticks before Chrome start.
                    body = (
                        '<?xml version="1.0" encoding="utf-8" standalone="yes" ?>\n'
                        "<map>\n"
                        f'    <boolean name="{marker}" value="true" />\n'
                        "</map>\n"
                    )
                updated = _force_command_line_flag_in_prefs_xml(body, marker)
                if updated is None:
                    logger.warning("skip prefs %s on %s (unusable XML)", prefs_path, serial)
                    continue
                if updated == body and f'{marker}" value="true"' in body:
                    any_ok = True
                    continue
                with tempfile.NamedTemporaryFile(
                    mode="w", encoding="utf-8", suffix=".xml", delete=False
                ) as tmp:
                    tmp.write(updated)
                    local_path = tmp.name
                pushed = adb.push(local_path, prefs_path, serial=serial)
                if not pushed.ok:
                    logger.warning(
                        "push chrome prefs failed on %s path=%s: %s",
                        serial,
                        prefs_path,
                        pushed.stderr,
                    )
                    continue
                adb.shell(f"chown {uid_gid} {prefs_path}", serial=serial)
                adb.shell(f"chmod 660 {prefs_path}", serial=serial)
                verify = adb.shell(f"cat {prefs_path}", serial=serial)
                if f'{marker}" value="true"' in (verify.stdout or ""):
                    any_ok = True
                else:
                    logger.warning(
                        "CommandLineOnNonRooted still not true after push on %s (%s)",
                        serial,
                        prefs_path,
                    )
            finally:
                if local_path:
                    try:
                        os.unlink(local_path)
                    except OSError:
                        pass
        if any_ok:
            # Chrome must relaunch to bind --remote-debugging-port; force-stop so the
            # next open_url starts with the CachedFlag + flag file actually applied.
            adb.shell(f"am force-stop {BROWSER_CHROMIUM}", serial=serial)
            logger.info("Enabled CommandLineOnNonRooted on %s (prefs + force-stop)", serial)
        return any_ok
    except Exception as exc:
        logger.warning("ensure_command_line_on_non_rooted failed on %s: %s", serial, exc)
        return False


def _push_text_to_device_paths(
    adb: AdbWrapper,
    serial: str,
    local_path: str,
    remote_paths: tuple[str, ...],
    *,
    label: str,
) -> str:
    """Push a host file to the first writable device path; return path or ""."""
    for remote in remote_paths:
        pushed = adb.push(local_path, remote, serial=serial)
        if pushed.ok:
            adb.shell(f"chmod 644 {remote} 2>/dev/null; true", serial=serial)
            return remote
        low = (pushed.stderr or "").lower()
        if "read-only" in low or "read only" in low:
            logger.warning("%s push RO on %s path=%s", label, serial, remote)
            continue
        logger.warning(
            "%s push failed on %s path=%s: %s", label, serial, remote, pushed.stderr
        )
    return ""


def _read_chrome_flags_body(adb: AdbWrapper, serial: str) -> str:
    for path in CHROME_FLAGS_PUSH_PATHS:
        cat = adb.shell(f"cat {path} 2>/dev/null", serial=serial)
        body = cat.stdout or ""
        if body.strip() and "--user-agent=" in body:
            return body
    return ""


def write_chromium_flags(adb: AdbWrapper, serial: str, profile: BrowserSessionProfile, *, phone_index: int = 0) -> bool:
    flags = build_chromium_command_line(profile, phone_index=phone_index)
    # Opera reads the same switches but expects the `opera` binary name prefix.
    opera_flags = ("opera " + flags[len("chrome ") :]) if flags.startswith("chrome ") else flags
    local_path = ""
    flags_remote = ""
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", suffix=".txt", delete=False) as tmp:
            tmp.write(flags)
            local_path = tmp.name
        flags_remote = _push_text_to_device_paths(
            adb,
            serial,
            local_path,
            CHROME_FLAGS_PUSH_PATHS,
            label="chrome flags",
        )
        if not flags_remote:
            logger.warning(
                "adb push chrome flags failed on %s (tmp+root RO) — browse without flags",
                serial,
            )
            return False
        # Mirror to sibling paths when primary push succeeded (best-effort).
        adb.shell(
            f"cp {flags_remote} {CHROME_FLAGS_PATH_ROOT} 2>/dev/null; "
            f"cp {flags_remote} {CHROME_FLAGS_PATH} 2>/dev/null; "
            f"cp {flags_remote} {WEBVIEW_FLAGS_PATH} 2>/dev/null; "
            f"cp {flags_remote} {WEBVIEW_FLAGS_PATH_ROOT} 2>/dev/null; "
            f"chmod 644 {CHROME_FLAGS_PATH} {CHROME_FLAGS_PATH_ROOT} "
            f"{WEBVIEW_FLAGS_PATH} {WEBVIEW_FLAGS_PATH_ROOT} 2>/dev/null; true",
            serial=serial,
        )
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", suffix=".txt", delete=False) as tmp_op:
            tmp_op.write(opera_flags)
            opera_local = tmp_op.name
        try:
            opera_remote = _push_text_to_device_paths(
                adb,
                serial,
                opera_local,
                (OPERA_FLAGS_PATH, OPERA_FLAGS_PATH_ROOT),
                label="opera flags",
            )
            if opera_remote:
                adb.shell(
                    f"cp {opera_remote} {OPERA_FLAGS_PATH} 2>/dev/null; "
                    f"cp {opera_remote} {OPERA_FLAGS_PATH_ROOT} 2>/dev/null; "
                    f"chmod 644 {OPERA_FLAGS_PATH} {OPERA_FLAGS_PATH_ROOT} 2>/dev/null; true",
                    serial=serial,
                )
        finally:
            try:
                os.unlink(opera_local)
            except OSError:
                pass
        ensure_command_line_on_non_rooted(adb, serial)
        body = _read_chrome_flags_body(adb, serial)
        if "--user-agent=" not in body:
            logger.warning("chrome flags missing UA on %s after push", serial)
            return False
        if profile.model not in body:
            logger.warning("chrome flags missing model %r on %s", profile.model, serial)
            return False
        return True
    except OSError as exc:
        logger.error("write_chromium_flags failed on %s: %s", serial, exc)
        return False
    finally:
        if local_path:
            try:
                os.unlink(local_path)
            except OSError:
                pass


def write_firefox_user_agent_override(
    adb: AdbWrapper, serial: str, profile: BrowserSessionProfile
) -> bool:
    """Set general.useragent.override in Fenix prefs.js so FF ≠ sticky getprop UA.

    Firefox ignores chrome-command-line; without this, Cloudflare sees the MuMu
    boot-time model forever on Path1/2 Firefox sequences.
    """
    from automation.config import BROWSER_FIREFOX

    ua = (profile.user_agent or "").replace("\\", "\\\\").replace('"', '\\"')
    if not ua:
        return False
    find = adb.shell(
        f"ls /data/data/{BROWSER_FIREFOX}/files/mozilla/*.default/prefs.js 2>/dev/null",
        serial=serial,
    )
    paths = [
        p.strip()
        for p in (find.stdout or "").splitlines()
        if p.strip().endswith("prefs.js")
    ]
    if not paths:
        # Profile may not exist yet — seed a default path Fenix will adopt.
        paths = [f"/data/data/{BROWSER_FIREFOX}/files/mozilla/pharmflow.default/prefs.js"]
        adb.shell(
            f"mkdir -p /data/data/{BROWSER_FIREFOX}/files/mozilla/pharmflow.default",
            serial=serial,
        )
    ok_any = False
    line = f'user_pref("general.useragent.override", "{ua}");'
    for prefs_path in paths:
        cat = adb.shell(f"cat {prefs_path} 2>/dev/null", serial=serial)
        body = cat.stdout or ""
        # Drop prior override lines, then append.
        kept = [
            ln
            for ln in body.splitlines()
            if "general.useragent.override" not in ln
        ]
        kept.append(line)
        new_body = "\n".join(kept) + "\n"
        local_path = ""
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", suffix=".js", delete=False
            ) as tmp:
                tmp.write(new_body)
                local_path = tmp.name
            pushed = adb.push(local_path, prefs_path, serial=serial)
            if pushed.ok:
                owner = adb.shell(
                    f"stat -c '%u:%g' /data/data/{BROWSER_FIREFOX}", serial=serial
                )
                uid_gid = (owner.stdout or "").strip() or "shell:shell"
                adb.shell(f"chown {uid_gid} {prefs_path}", serial=serial)
                adb.shell(f"chmod 660 {prefs_path}", serial=serial)
                ok_any = True
        finally:
            if local_path:
                try:
                    os.unlink(local_path)
                except OSError:
                    pass
    if ok_any:
        adb.shell(f"am force-stop {BROWSER_FIREFOX}", serial=serial)
        logger.info(
            "Firefox UA override model=%s serial=%s", profile.model, serial
        )
    return ok_any


def apply_browser_session(
    adb: AdbWrapper, serial: str, profile: BrowserSessionProfile, *, phone_index: int = 0
) -> dict[str, Any]:
    written = write_chromium_flags(adb, serial, profile, phone_index=phone_index)
    adb.shell(f"settings put global user_agent '{profile.user_agent}'", serial=serial)
    adb.shell(f"settings put secure user_agent '{profile.user_agent}'", serial=serial)
    ff_ok = False
    try:
        ff_ok = write_firefox_user_agent_override(adb, serial, profile)
    except Exception as exc:
        logger.debug("Firefox UA override soft-fail serial=%s: %s", serial, exc)
    android_id_ok = False
    android_id_live = ""
    if profile.android_id:
        adb.shell(f"settings put secure android_id {profile.android_id}", serial=serial)
        android_id_live = read_secure_android_id(adb, serial)
        android_id_ok = android_id_live == profile.android_id
        if not android_id_ok:
            logger.warning(
                "android_id write mismatch serial=%s want=%s got=%s",
                serial,
                profile.android_id,
                android_id_live,
            )
    adb.shell(f"am force-stop {BROWSER_CHROMIUM}", serial=serial)
    session_ok = (not profile.android_id) or android_id_ok
    if not written:
        logger.warning(
            "chrome flags not written on %s — continuing browse (degraded UA/CDP)",
            serial,
        )
    return {
        "ok": session_ok,
        "profile_key": profile.key,
        "model": profile.model,
        "brand": profile.brand,
        "user_agent": profile.user_agent,
        "user_agent_written": written,
        "firefox_ua_ok": ff_ok,
        "android_id": profile.android_id,
        "android_id_live": android_id_live,
        "android_id_ok": android_id_ok,
        "source": profile.source,
    }


def verify_browser_headers(
    adb: AdbWrapper,
    serial: str,
    profile: BrowserSessionProfile,
) -> BrowserHeaderReport:
    report = BrowserHeaderReport(
        serial=serial,
        passed=False,
        profile_key=profile.key,
        expected_model=profile.model,
        chrome_flags_ok=False,
    )
    cat_body = _read_chrome_flags_body(adb, serial)
    body = cat_body
    if not body or "--user-agent=" not in body:
        report.failures.append("chrome-command-line missing or empty on device")
        return report
    report.user_agent_in_flags = body
    report.chrome_flags_ok = profile.model in body
    if not report.chrome_flags_ok:
        report.failures.append(f"model {profile.model!r} not found in chrome-command-line")
    if "AutomationControlled" not in body:
        report.failures.append("missing --disable-blink-features=AutomationControlled")
    report.passed = report.chrome_flags_ok and not report.failures
    return report


def scramble_browser_session(
    adb: AdbWrapper,
    serial: str,
    phone_index: int,
) -> tuple[BrowserSessionProfile, dict[str, Any]]:
    """New session every scramble: new retail model/UA + verified new android_id."""
    avoid = _last_model_by_serial.get(serial, "")
    last_aid = _last_android_id_by_serial.get(serial, "") or read_secure_android_id(adb, serial)
    # Retry until android_id actually differs from the previous sequence.
    # MuMu ARM does not apply `settings put secure android_id` live (it lands on
    # next cold boot), so the read-back never matches and the old loop burned up to
    # 4 full applies (~6 ADB cmds each) per scramble — the #1 isolation time sink.
    # The model/UA write (what Mantis actually sees) succeeds on the first apply,
    # so retry at most once and otherwise accept the written android_id.
    profile: BrowserSessionProfile | None = None
    applied: dict[str, Any] = {}
    for attempt in range(2):
        aid = _random_android_id()
        if aid == last_aid:
            continue
        profile = profile_from_retail_pool(
            adb, serial, android_id=aid, avoid_model=avoid
        )
        applied = apply_browser_session(adb, serial, profile, phone_index=phone_index)
        live = str(applied.get("android_id_live") or "")
        if live and live != last_aid and live == profile.android_id:
            break
        if attempt == 0:
            # Model/UA/flags all changed on this apply — the write is in. MuMu ARM
            # just won't report the new android_id until reboot; don't re-apply.
            logger.debug(
                "scramble serial=%s android_id read-back %r != %r (MuMu ARM live lag) — accepting model/UA change",
                serial,
                live,
                profile.android_id if profile else "",
            )
            break
        # Force another id if device kept the old value (second attempt only).
        last_aid = live or last_aid
    if profile is None:
        profile = profile_from_retail_pool(adb, serial, avoid_model=avoid)
        applied = apply_browser_session(adb, serial, profile, phone_index=phone_index)
    _last_model_by_serial[serial] = profile.model
    _last_android_id_by_serial[serial] = profile.android_id
    logger.info(
        "Browser scramble serial=%s brand=%s model=%s android_id=%s flags=%s source=%s",
        serial,
        profile.brand,
        profile.model,
        profile.android_id,
        applied.get("user_agent_written"),
        profile.source,
    )
    return profile, applied


def ensure_browser_identity_before_browse(
    adb: AdbWrapper,
    serial: str,
    phone_index: int,
    *,
    scramble: bool = True,
) -> tuple[BrowserSessionProfile, BrowserHeaderReport]:
    if scramble:
        profile, _applied = scramble_browser_session(adb, serial, phone_index)
    else:
        profile = profile_from_device(adb, serial)
        apply_browser_session(adb, serial, profile, phone_index=phone_index)
    report = verify_browser_headers(adb, serial, profile)
    if not report.passed:
        logger.warning("Browser header verify failed serial=%s: %s", serial, report.failures)
        apply_browser_session(adb, serial, profile, phone_index=phone_index)
        report = verify_browser_headers(adb, serial, profile)
    return profile, report
