#!/usr/bin/env python3
"""Start Mantis inject proxies for phones 0..N-1 (default 5).

  py -u scripts/run_mantis_inject_proxies.py
  py -u scripts/run_mantis_inject_proxies.py --phones 5 --install-ca

Phone traffic: http_proxy 127.0.0.1:8218+i → inject → Tor 8118+i
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import automation.no_window  # noqa: E402,F401  (kill child console-window flashes)

from automation.browse_proxy import guest_proxy_healthy, pin_guest_proxy  # noqa: E402
from automation.mantis_inject_ca import ensure_ca_files, install_ca_on_device  # noqa: E402
from automation.mantis_inject_proxy import (  # noqa: E402
    ensure_inject_for_phone,
    start_inject_proxies,
)
from wizard.mumu_farm_ops import MuMuFarmOps  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("mantis_inject")


def _farm_lane_alive() -> bool:
    """True when a run_farm_354.py lane process is currently alive.

    The farm owns the inject proxies in-process, so this runner must stand down
    whenever the farm is up — two inject generations on different port bases is
    the exact split-brain that killed phone internet on 2026-09-10.
    """
    try:
        import psutil

        for p in psutil.process_iter(["pid", "cmdline"]):
            try:
                cmd = " ".join(str(x) for x in (p.info.get("cmdline") or []))
            except Exception:
                continue
            if "run_farm_354.py" in cmd:
                return True
    except Exception:
        return False
    return False


def _another_injector_running() -> bool:
    """True when a second run_mantis_inject_proxies lane is already alive.

    Duplicate injector lanes race to pin guest proxies — each pins 127.0.0.1:port
    values from its own index span, so a phone ends up pointed at a port whose
    tor/inject listener belongs to the OTHER lane (or nothing at all). Observed
    twice: two lanes 3s apart left phones pinned to dead ports = zero internet.
    """
    try:
        import psutil

        me = os.getpid()
        for p in psutil.process_iter(["pid", "cmdline"]):
            try:
                if p.info["pid"] == me:
                    continue
                cmd = " ".join(str(x) for x in (p.info.get("cmdline") or []))
            except Exception:
                continue
            if "run_mantis_inject_proxies.py" in cmd:
                return True
    except Exception:
        pass
    return False


def main() -> int:
    if _another_injector_running():
        log.warning("another run_mantis_inject_proxies lane is alive — refusing duplicate (would race proxy pins)")
        return 0
    # Single-owner rule: when the farm lane is alive it owns inject in-process
    # (absolute phone indexes). This roster-indexed runner would only create a
    # second port-divergent generation — stand down instead.
    try:
        if _farm_lane_alive():
            log.info("farm lane owns inject in-process — standalone runner standing down (no duplicate generation)")
            return 0
    except Exception:  # noqa: BLE001 — probe failure must not block fallback use
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--phones", type=int, default=11)
    ap.add_argument("--install-ca", action="store_true", default=True)
    ap.add_argument("--no-install-ca", action="store_true")
    ap.add_argument("--once", action="store_true", help="Start proxies, arm phones, exit (leave threads)")
    args = ap.parse_args()
    install_ca = bool(args.install_ca) and not bool(args.no_install_ca)

    ensure_ca_files()
    idxs = list(range(max(1, int(args.phones))))
    proxies = start_inject_proxies(idxs)
    log.info("started %d inject proxies", len(proxies))

    farm = MuMuFarmOps()
    try:
        farm.refresh_serials()
    except Exception as exc:
        log.warning("refresh_serials: %s", exc)

    for inst in farm.list_instances():
        if inst.index is None or inst.index not in idxs:
            continue
        if not inst.adb_serial:
            continue
        if install_ca:
            try:
                ok = install_ca_on_device(farm.adb, inst.adb_serial)
                log.info("CA phone=%s serial=%s ok=%s", inst.index, inst.adb_serial, ok)
            except Exception as exc:
                log.warning("CA phone=%s failed: %s", inst.index, exc)
        info = ensure_inject_for_phone(
            farm.adb, inst.adb_serial, int(inst.index), install_ca=False
        )
        # Idempotent verify — ad-fill / identity scramble can leave :0 after arm.
        pinned = pin_guest_proxy(
            farm.adb, inst.adb_serial, int(inst.index), attempts=3
        )
        info = dict(info or {})
        info["http_proxy"] = pinned
        info["proxy_ok"] = guest_proxy_healthy(pinned, int(inst.index))
        log.info("armed %s → %s", inst.name, info)

    if args.once:
        # Keep process alive briefly so callers can verify ports.
        time.sleep(2)
        return 0

    # Keep SSP creatives warm so MITM/CDP paint is instant (page loads, ads already ready).
    try:
        from automation.dabflow_mantis_client_patch import ensure_ssp_cache_warm, prefetch_ssp_ads

        n = len(prefetch_ssp_ads(force=True) or [])
        log.info("SSP cache primed creatives=%d", n)
    except Exception as exc:
        log.warning("SSP cache prime soft-fail: %s", exc)

    log.info("inject proxies running — Ctrl+C to stop")
    try:
        while True:
            time.sleep(30)
            try:
                from automation.dabflow_mantis_client_patch import ensure_ssp_cache_warm

                ensure_ssp_cache_warm()
            except Exception:
                pass
            for p in proxies:
                log.info(
                    "stats phone=%d listen=%d %s",
                    p.phone_index,
                    p.listen_port,
                    p.stats,
                )
            try:
                from automation.mantis_inject_proxy import _publish_inject_stats

                _publish_inject_stats(proxies)
            except Exception:
                pass
    except KeyboardInterrupt:
        log.info("stopping")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
