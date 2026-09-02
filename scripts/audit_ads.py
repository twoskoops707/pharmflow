"""Audit AD sequences: verify they target genuinely DIFFERENT ads.

Read-only audit of C:\\CPharm\\automation\\recordings\\sequences\\base\\{ceramic,quartz,titanium}\\*_ad.json
(the "smoke" folder is ignored). Does NOT modify sequences or touch the farm.

Checks:
  1. dabflow (ad_page, ad_index) vs filename — reconciliation.
  2. Actual "Tap ad" step coordinates per file.
  3. Distinct ad slots vs distinct ad-tap coordinates; do different ad_index
     values map to different pixels?
  4. run_farm_354._parse_ad_key distribution; files where the key is None.
  5. Per material/concentrate/heater combo: do the ad variants hit different
     spots/pages?

Output: stdout + C:\\CPharm\\logs\\sequence_audit_ads.txt
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

BASE = Path(r"C:\CPharm\automation\recordings\sequences\base")
MATERIALS = ("ceramic", "quartz", "titanium")
OUT_PATH = Path(r"C:\CPharm\logs\sequence_audit_ads.txt")


# --- exact copy of run_farm_354._parse_ad_key -------------------------------
def _parse_ad_key(stem: str) -> str | None:
    """Stable ad identity: home:N | stats:N | glass:N | settings:N."""
    m = re.search(r"homead(\d+)", stem)
    if m:
        return f"home:{m.group(1)}"
    m = re.search(r"_on(stats|glass|settings)_ad(\d+)_ad$", stem)
    if m:
        return f"{m.group(1)}:{m.group(2)}"
    m = re.search(r"_(stats|glass|settings)_ad(\d+)_ad$", stem)
    if m:
        return f"{m.group(1)}:{m.group(2)}"
    return None


# --- filename parsing --------------------------------------------------------
# dabflow "ad_tab" values map to the short page names used in filenames.
TAB_TO_PAGE = {"glass_art": "glass", "glass": "glass", "settings": "settings", "stats": "stats", "home": "home"}


def parse_filename(stem: str) -> tuple[str | None, int | None, str]:
    """Return (page, index, path_kind) parsed purely from the filename."""
    m = re.search(r"_p3a_homead(\d+)_ad$", stem)
    if m:
        return "home", int(m.group(1)), "p3a"
    m = re.search(r"_p3b_(glass|settings|stats)_ad(\d+)_ad$", stem)
    if m:
        return m.group(1), int(m.group(2)), "p3b"
    m = re.search(r"_p3([cd])_[\w]+?_on(glass|settings|stats)_ad(\d+)_ad$", stem)
    if m:
        return m.group(2), int(m.group(3)), f"p3{m.group(1)}"
    return None, None, "?"


def parse_combo(stem: str) -> str:
    m = re.match(r"^(ceramic|quartz|titanium)_(.+?)_p3[a-d]_", stem)
    if m:
        return f"{m.group(1)}|{m.group(2)}"
    return stem


def coord_base(v) -> float | None:
    if isinstance(v, dict):
        return v.get("base")
    if isinstance(v, (int, float)):
        return v
    return None


def main() -> int:
    lines: list[str] = []

    def emit(s: str = "") -> None:
        lines.append(s)

    files: list[Path] = []
    for mat in MATERIALS:
        files.extend(sorted((BASE / mat).glob("*_ad.json")))

    emit("=" * 78)
    emit("AD SEQUENCE AUDIT — do ad sequences click DIFFERENT ads?")
    emit(f"Scanned: {BASE} ({', '.join(MATERIALS)}; smoke ignored)")
    emit(f"Total *_ad.json files: {len(files)}")
    emit("=" * 78)

    defects: list[str] = []
    records = []  # per-file dict

    for path in files:
        stem = path.stem
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:  # unreadable file is a defect
            defects.append(f"UNREADABLE JSON: {path} ({exc})")
            continue

        dab = data.get("dabflow") or {}
        # p3a uses "ad_page"; p3b/p3c/p3d use "ad_tab" (e.g. "glass_art").
        raw_page = dab.get("ad_page") or dab.get("ad_tab")
        dab_page = TAB_TO_PAGE.get(raw_page, raw_page) if raw_page else None
        dab_index = dab.get("ad_index")

        fn_page, fn_index, path_kind = parse_filename(stem)
        if fn_page is None:
            defects.append(f"FILENAME UNPARSED (no page/index pattern): {stem}")
        if dab_page is None or dab_index is None:
            defects.append(f"MISSING dabflow ad_page/ad_index: {stem}")
        elif fn_page is not None and (dab_page != fn_page or dab_index != fn_index):
            defects.append(
                f"MISMATCH dabflow vs filename: {stem} "
                f"dabflow=({dab_page},{dab_index}) filename=({fn_page},{fn_index})"
            )

        # Extract actual ad-tap step(s) + count the ad-reveal scroll swipes
        # that position the page before the tap ("Scroll to bottom (...-ads-N x/y)").
        # Ads on the same page share a nominal pixel; WHICH ad is under that
        # pixel is determined by how far the page was scrolled.
        taps = []
        ad_scrolls = 0
        for step in data.get("steps", []):
            desc = step.get("description", "")
            if step.get("action") == "swipe" and re.search(r"-ads-\d+ \d+/\d+", desc):
                ad_scrolls += 1
            if step.get("action") == "tap" and "Tap ad" in desc:
                params = step.get("params", {})
                x = coord_base(params.get("x"))
                y = coord_base(params.get("y"))
                taps.append((x, y, desc))
        if not taps:
            defects.append(f"NO 'Tap ad' STEP FOUND: {stem}")
        elif len(taps) > 1:
            defects.append(f"MULTIPLE 'Tap ad' STEPS ({len(taps)}): {stem}")

        ad_key = _parse_ad_key(stem)
        if ad_key is None:
            defects.append(f"_parse_ad_key returned None: {stem}")

        # Cross-check: the tap description names the slot too ("Tap ad (home slot 0)")
        tap = taps[0] if taps else (None, None, "")
        if tap[2]:
            md = re.search(r"Tap ad \((\w+) slot (\d+)\)", tap[2])
            if md:
                d_page = TAB_TO_PAGE.get(md.group(1), md.group(1))
                d_idx = int(md.group(2))
                eff_page = dab_page if dab_page is not None else fn_page
                eff_idx = dab_index if dab_index is not None else fn_index
                if (d_page, d_idx) != (eff_page, eff_idx):
                    defects.append(
                        f"TAP-DESC MISMATCH: {stem}: step says ({d_page},{d_idx}) "
                        f"but file identity is ({eff_page},{eff_idx})"
                    )

        records.append(
            {
                "stem": stem,
                "material": path.parent.name,
                "combo": parse_combo(stem),
                "path_kind": path_kind,
                "page": dab_page if dab_page is not None else fn_page,
                "index": dab_index if dab_index is not None else fn_index,
                "x": tap[0],
                "y": tap[1],
                "tap_desc": tap[2],
                "ad_scrolls": ad_scrolls,
                "ad_key": ad_key,
            }
        )

    # ---- 3. distinct slots, coordinates and scroll depths --------------------
    slot_coords: dict[tuple, Counter] = defaultdict(Counter)
    slot_scrolls: dict[tuple, Counter] = defaultdict(Counter)
    all_slots = set()
    all_coords = set()
    for r in records:
        if r["page"] is None or r["x"] is None:
            continue
        slot = (r["page"], r["index"])
        coord = (r["x"], r["y"])
        all_slots.add(slot)
        all_coords.add(coord)
        slot_coords[slot][coord] += 1
        slot_scrolls[slot][r["ad_scrolls"]] += 1

    emit()
    emit("--- DISTINCT AD TARGETS ---")
    emit(f"Distinct ad slots (page, ad_index): {len(all_slots)}")
    emit(f"Distinct raw ad-tap (x,y) coordinates: {len(all_coords)} (includes per-file humanization jitter)")
    emit()
    emit("Per slot: tap coordinate envelope (min..max) + scroll depth (ad-reveal swipes before tap):")
    for slot in sorted(all_slots):
        coords = slot_coords[slot]
        xs = [c[0] for c in coords]
        ys = [c[1] for c in coords]
        scr = dict(sorted(slot_scrolls[slot].items()))
        emit(
            f"  {slot[0]}:{slot[1]}  x {min(xs)}..{max(xs)}  y {min(ys)}..{max(ys)}"
            f"  ({len(coords)} jittered variants)  scroll_depth(s): {scr}"
        )

    # Discriminator check: on the same page, different ad_index must differ in
    # HOW the ad is reached (scroll depth) even if the nominal tap pixel is the
    # same (list pages reuse the tap zone; scroll depth selects the ad).
    emit()
    emit("Same-page discrimination (what actually selects WHICH ad):")
    page_idx_scroll: dict[str, dict[int, set]] = defaultdict(lambda: defaultdict(set))
    for r in records:
        if r["page"] is None:
            continue
        page_idx_scroll[r["page"]][r["index"]].add(r["ad_scrolls"])
    ambiguous_pages = []
    for page in sorted(page_idx_scroll):
        idx_map = {i: sorted(s) for i, s in sorted(page_idx_scroll[page].items())}
        emit(f"  page={page}: scroll depths per ad_index: {idx_map}")
        depth_owner: dict[int, list[int]] = defaultdict(list)
        for i, depths in idx_map.items():
            for d in depths:
                depth_owner[d].append(i)
        clashes = {d: ix for d, ix in depth_owner.items() if len(ix) > 1}
        if clashes:
            ambiguous_pages.append(page)
            emit(f"    !! AMBIGUOUS: same scroll depth used by multiple ad_index: {clashes}")
        else:
            emit("    OK: every ad_index reaches its ad via a unique scroll depth.")

    # ---- 4. _parse_ad_key distribution --------------------------------------
    emit()
    emit("--- _parse_ad_key (run_farm_354.py) DISTRIBUTION ---")
    key_counter = Counter(r["ad_key"] for r in records)
    none_count = key_counter.pop(None, 0)
    for key, n in sorted(key_counter.items()):
        # which path kinds feed this key
        kinds = Counter(r["path_kind"] for r in records if r["ad_key"] == key)
        kd = ", ".join(f"{k}:{v}" for k, v in sorted(kinds.items()))
        emit(f"  {key:<12} {n:>4} files  ({kd})")
    emit(f"  (None)       {none_count:>4} files  <-- would be treated as non-ad, NO rotation lock")
    emit(f"Distinct ad keys: {len(key_counter)}")

    # Does the key distinguish the real distinct targets? Verify a 1:1 mapping
    # between ad_key and (page, ad_index) slot in both directions.
    emit()
    key_slots: dict[str, set] = defaultdict(set)
    slot_keys: dict[tuple, set] = defaultdict(set)
    for r in records:
        if r["ad_key"] and r["page"] is not None:
            key_slots[r["ad_key"]].add((r["page"], r["index"]))
            slot_keys[(r["page"], r["index"])].add(r["ad_key"])
    bad_key = {k: sorted(s) for k, s in key_slots.items() if len(s) > 1}
    bad_slot = {s: sorted(k) for s, k in slot_keys.items() if len(k) > 1}
    if bad_key or bad_slot:
        for k, s in sorted(bad_key.items()):
            emit(f"  !! key {k} covers multiple slots: {s}")
        for s, k in sorted(bad_slot.items()):
            emit(f"  !! slot {s} covered by multiple keys: {k}")
    else:
        emit("ad_key <-> (page, ad_index) slot is a perfect 1:1 mapping — the farm's")
        emit("rotation lock distinguishes exactly the real distinct ad targets.")

    # ---- 5. per-combo variant diversity --------------------------------------
    emit()
    emit("--- PER material/concentrate/heater COMBO ---")
    combo_map: dict[str, list] = defaultdict(list)
    for r in records:
        combo_map[r["combo"]].append(r)
    n_combos = len(combo_map)
    sizes = Counter(len(v) for v in combo_map.values())
    emit(f"Combos found: {n_combos}; ad-files-per-combo distribution: {dict(sorted(sizes.items()))}")
    bad_combos = 0
    combo_slot_counts = Counter()
    for combo, rs in sorted(combo_map.items()):
        slots = {(r["page"], r["index"]) for r in rs if r["page"] is not None}
        pages = {r["page"] for r in rs if r["page"] is not None}
        combo_slot_counts[(len(rs), len(slots), len(pages))] += 1
        if len(rs) > 1 and len(slots) < 2:
            bad_combos += 1
            defects.append(
                f"COMBO LOW DIVERSITY: {combo}: {len(rs)} ad files but only "
                f"{len(slots)} distinct ad slot(s)"
            )
    emit("(files, distinct_slots, distinct_pages) -> combo count:")
    for sig, n in sorted(combo_slot_counts.items()):
        emit(f"  files={sig[0]} slots={sig[1]} pages={sig[2]} -> {n} combos")
    if bad_combos == 0:
        emit("Every combo's ad variants target genuinely different slots/pages.")

    # ---- defects -------------------------------------------------------------
    emit()
    emit("--- DEFECTS ---")
    if defects:
        emit(f"{len(defects)} defect(s):")
        for d in defects[:200]:
            emit(f"  - {d}")
        if len(defects) > 200:
            emit(f"  ... and {len(defects) - 200} more")
    else:
        emit("None. dabflow blocks match filenames; every file has exactly one 'Tap ad'")
        emit("step; _parse_ad_key classifies every ad file.")

    # ---- verdict --------------------------------------------------------------
    emit()
    emit("--- VERDICT ---")
    emit(
        f"(a) Genuinely distinct ad targets: {len(all_slots)} slots (4 pages) — "
        f"{len(all_coords)} raw tap coordinates after humanization jitter."
    )
    if not ambiguous_pages:
        emit("(b) YES — different ad sequences click DIFFERENT ads. On each page the")
        emit("    ad is selected by scroll depth (each ad_index scrolls a different")
        emit("    distance before tapping the on-screen ad zone), and home slots also")
        emit("    use distinct scroll counts. No two ad_index values on the same page")
        emit("    share a scroll depth.")
    else:
        emit(f"(b) NO for pages {ambiguous_pages}: same scroll depth reaches multiple")
        emit("    ad_index values — those sequences likely click the SAME ad.")
    emit(f"(c) Files unclassified by _parse_ad_key: {none_count}")
    emit(f"(d) Total defects: {len(defects)}")

    report = "\n".join(lines)
    print(report)
    try:
        OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        OUT_PATH.write_text(report + "\n", encoding="utf-8")
        print(f"\nReport written to {OUT_PATH}")
    except Exception as exc:
        print(f"\nWARNING: could not write {OUT_PATH}: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
