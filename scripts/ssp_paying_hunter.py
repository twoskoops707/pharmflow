"""Background hunter: re-probe Mantis SSP until a paying creative appears.

Does not invent ads. When paying inventory is found, persists full creative
payloads to ``C:\\CPharm\\logs\\ssp_paying_fill.json`` so farm workers (separate
process) can ingest them. Also drops ``SSP_FORCE_REFRESH.flag`` as a wake
signal — farm consume keeps paying fill (does not wipe it).
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import automation.no_window  # noqa: E402,F401  — hide tor/adb consoles
from automation.dabflow_mantis_client_patch import (  # noqa: E402
    _clear_ssp_house_only,
    _persist_paying_fill,
    _store_ssp_ads,
    clear_ssp_cache,
    clear_ssp_paying_fill_file,
    prefetch_ssp_ads_prefer_paying,
    ssp_ads_paying_count,
)
from automation.tor_manager import TorManager  # noqa: E402

LOG = Path(r"C:\CPharm\logs")
HB = LOG / "ssp_paying_hunter_heartbeat.txt"
OUT = LOG / "ssp_paying_hunter.json"
FLAG = LOG / "SSP_FORCE_REFRESH.flag"
FILL = LOG / "ssp_paying_fill.json"
STOP = LOG / "SSP_HUNTER_STOP.flag"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(LOG / "ssp_paying_hunter.log", encoding="utf-8"),
    ],
)
log = logging.getLogger("ssp_hunter")


def _hb(msg: str) -> None:
    try:
        HB.write_text(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}\n", encoding="utf-8")
    except OSError:
        pass


def _newnym_all(tor: TorManager) -> int:
    ok = 0
    for idx in range(6):
        try:
            if tor._control_newnym(idx):
                ok += 1
        except Exception:
            pass
    return ok


def main() -> int:
    os.environ.setdefault("PYTHONPATH", str(ROOT))
    LOG.mkdir(parents=True, exist_ok=True)
    tor = TorManager(ROOT)
    round_n = 0
    last_pay = 0
    house_streak = 0
    while not STOP.is_file():
        round_n += 1
        if round_n % 3 == 1:
            nym = _newnym_all(tor)
            time.sleep(2.0)  # Tor NEWNYM settle
        else:
            nym = 0
        # Clear this process cache only — do not delete ssp_paying_fill.json
        # here on every round (paying handoff). House streak clears it below.
        clear_ssp_cache()
        ads = prefetch_ssp_ads_prefer_paying(
            attempts=12, delay_s=0.45, allow_house_fallback=False
        ) or []
        paying = ssp_ads_paying_count(ads)
        last_pay = paying
        payload = {
            "ts": time.time(),
            "round": round_n,
            "paying": paying,
            "n": len(ads),
            "newnym": nym,
            "zones": [
                a.get("zone_id")
                for a in ads
                if isinstance(a, dict)
            ][:12],
            "fill_path": str(FILL),
        }
        try:
            OUT.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        except OSError:
            pass
        if paying > 0:
            house_streak = 0
            _store_ssp_ads(ads, persist=True)
            _persist_paying_fill(ads)
            _clear_ssp_house_only()
            try:
                FLAG.write_text(
                    json.dumps(
                        {
                            "reason": "ssp_paying_hunter",
                            "paying": paying,
                            "ts": time.time(),
                            "fill": str(FILL),
                        }
                    )
                    + "\n",
                    encoding="utf-8",
                )
            except OSError:
                pass
            _hb(f"PAYING={paying} n={len(ads)} round={round_n} newnym={nym} fill={FILL.name}")
            log.info(
                "paying fill locked paying=%d round=%d fill=%s",
                paying,
                round_n,
                FILL,
            )
            time.sleep(45.0)
        else:
            house_streak += 1
            # Live SSP is house-only — drop stale shared fill so farm does not
            # keep painting the same one paying creative (e.g. Viking) forever.
            if house_streak >= 4:
                cleared = clear_ssp_paying_fill_file(
                    reason=f"hunter_house_streak={house_streak}"
                )
                clear_ssp_cache()
                house_streak = 0
                _hb(
                    f"house_only round={round_n} newnym={nym} "
                    f"cleared_stale_fill={cleared}"
                )
                log.info(
                    "house-only streak — cleared stale paying fill round=%d cleared=%s",
                    round_n,
                    cleared,
                )
            else:
                _hb(f"house_only round={round_n} newnym={nym} streak={house_streak}")
                log.info(
                    "still house-only round=%d newnym=%d streak=%d",
                    round_n,
                    nym,
                    house_streak,
                )
            time.sleep(20.0)
    _hb(f"stopped last_pay={last_pay}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
