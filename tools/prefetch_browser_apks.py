"""Prefetch farm browser APKs so they ship INSIDE PharmFlow.exe.

CI runs this before ``pyinstaller``; the APKs land in ``wizard/bundled/apks/``
and ``PharmFlow.spec`` embeds that folder as PyInstaller datas. At runtime the
catalog and ``browser_setup`` find them first (``_MEIPASS/bundled/apks``), so
browser installs work offline and never depend on flaky public mirrors.

Chromium's public mirrors were shut down (download-chromium.appspot.com 500s,
the chromium-browser-snapshots bucket no longer lists or serves objects), so
the script still tries the catalog's primary source, then logs honestly when
it fails. The other four browsers (Firefox, Brave, DuckDuckGo, Opera) resolve
from live public sources and are embedded.

Usage:
    python tools/prefetch_browser_apks.py [--out <dir>]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent
_ROOT = _TOOLS_DIR.parent
for _p in (str(_ROOT), str(_ROOT / "automation"), str(_ROOT / "wizard")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from automation.browser_apk_catalog import BROWSER_APK_SPECS  # noqa: E402


def _progress(msg: str) -> None:
    print(msg, flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(_ROOT / "wizard" / "bundled" / "apks"))
    args = parser.parse_args()

    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)

    results: dict[str, dict] = {}
    failures: list[str] = []

    for spec in BROWSER_APK_SPECS:
        dest = out / spec.filename
        if dest.is_file() and dest.stat().st_size > 1_000_000:
            print(f"[skip] {spec.tag:10} already present ({dest.stat().st_size / 1e6:.1f} MB)")
            results[spec.tag] = {"file": spec.filename, "size": dest.stat().st_size}
            continue
        try:
            print(f"[fetch] {spec.tag:10} {spec.label} -> {dest.name}")
            path = _download_spec(spec, dest)
            size = path.stat().st_size
            print(f"[ok]    {spec.tag:10} {size / 1e6:.1f} MB")
            results[spec.tag] = {"file": spec.filename, "size": size}
        except Exception as exc:  # noqa: BLE001
            print(f"[FAIL]  {spec.tag:10} {exc}")
            failures.append(spec.tag)

    manifest = {
        "embedded_browsers": results,
        "failed": failures,
        "note": (
            "Chromium failures are expected: Google shut down the public "
            "chromium-browser-snapshots mirrors (appspot 500, bucket empty). "
            "Firefox/Brave/DuckDuckGo/Opera are embedded for offline install."
        ),
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"\nEmbedded {len(results)} browser(s) in {out}")
    print(json.dumps(manifest, indent=2))
    return 0


def _download_spec(spec, dest: Path) -> Path:
    """Download one browser APK. Chromium goes through its resolver chain."""
    from automation.browser_apk_catalog import (
        _http_download,
        resolve_brave_apk_url,
        resolve_chromium_apk_url,
        resolve_chromium_snapshot_apk_url,
        resolve_duckduckgo_apk_url,
        resolve_firefox_apk_url,
        resolve_opera_apk_url,
    )

    resolvers = {
        "chromium": (resolve_chromium_apk_url, resolve_chromium_snapshot_apk_url),
        "firefox": (resolve_firefox_apk_url,),
        "brave": (resolve_brave_apk_url,),
        "duckduckgo": (resolve_duckduckgo_apk_url,),
        "opera": (resolve_opera_apk_url,),
    }
    if spec.tag == "farmbrowser":
        return _copy_farmbrowser(dest)

    chain = resolvers.get(spec.tag)
    if not chain:
        raise RuntimeError(f"no resolver for {spec.tag}")
    last_exc: Exception | None = None
    for fn in chain:
        try:
            url = fn()
            if not url:
                continue
            return _http_download(url, dest, progress_cb=_progress)
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            print(f"      mirror failed: {exc}")
    raise RuntimeError(f"all mirrors failed for {spec.tag}: {last_exc}")


def _copy_farmbrowser(dest: Path) -> Path:
    """Embed the prebuilt FarmBrowser APK (no public mirror exists for it)."""
    import shutil

    sources = [
        _ROOT / "bundled" / "farmbrowser-debug.apk",
        Path(r"C:\CPharm\apks\farmbrowser-debug.apk"),
        _ROOT / "farmbrowser" / "app" / "build" / "outputs" / "apk" / "debug" / "app-debug.apk",
        _ROOT / "farmbrowser" / "app" / "build" / "outputs" / "apk" / "release" / "app-release.apk",
    ]
    for s in sources:
        if s.is_file() and s.stat().st_size > 100_000:
            shutil.copy2(s, dest)
            print(f"      embedded local FarmBrowser build: {s}")
            return dest
    raise RuntimeError(
        "FarmBrowser APK not found locally (C:\\CPharm\\apks or farmbrowser build output); "
        "not embedded this build"
    )


if __name__ == "__main__":
    sys.exit(main())