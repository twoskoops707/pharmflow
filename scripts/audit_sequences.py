"""Read-only structural audit of DabFlow automation sequence JSONs.

Scans C:\\PharmFlow\\automation\\recordings\\sequences\\base (excluding smoke/),
validates structure/coords/timing-variance, and writes a report to stdout
and C:\\PharmFlow\\logs\\sequence_audit_structure.txt.

Never modifies any sequence file.
"""

import json
import os
import sys
from collections import Counter, defaultdict

BASE_DIR = r"C:\PharmFlow\automation\recordings\sequences\base"
REPORT_PATH = r"C:\PharmFlow\logs\sequence_audit_structure.txt"
EXCLUDE_DIRS = {"smoke"}
MAX_EXAMPLES = 20

SCREEN_W = 900
SCREEN_H = 1600
TIMER_MIN_SECONDS = 75.0

REQUIRED_ACTIONS = [
    "rotate_identity",
    "ensure_fingerprint",
    "clear_cookies",
    "launch_app",
    "open_url",
    "close_app",
]


def classify(filename):
    stem = filename.lower()
    if stem.endswith("_complete.json"):
        return "complete"
    if stem.endswith("_ad.json"):
        return "ad"
    if stem.endswith("_halfway.json"):
        return "halfway"
    return "other"


def coord_value(v):
    """Return numeric base of a coordinate ({'base':N,...} or plain number), else None."""
    if isinstance(v, dict):
        b = v.get("base")
        return b if isinstance(b, (int, float)) else None
    if isinstance(v, (int, float)):
        return v
    return None


def find_files():
    files = []
    for root, dirs, names in os.walk(BASE_DIR):
        dirs[:] = [d for d in dirs if d.lower() not in EXCLUDE_DIRS]
        for n in names:
            if n.lower().endswith(".json"):
                files.append(os.path.join(root, n))
    return sorted(files)


def main():
    files = find_files()

    parse_failures = []          # (relpath, error)
    version_bad = []             # (relpath, value)
    width_bad = []
    height_bad = []
    missing_required = []        # (relpath, [what is missing])
    coord_oob = []               # (relpath, step_idx, detail)
    timer_missing = []           # complete sequences lacking >=75s wait
    fixed_scalar_waits = []      # (relpath, step_idx, value)
    min_eq_max_waits = []        # (relpath, step_idx, value)
    bad_wait_shape = []          # non-dict, non-scalar seconds

    n_wait_steps = 0
    n_range_waits = 0
    timer_wait_tuples = Counter()    # (min,max) for waits with min >= TIMER_MIN_SECONDS
    settle_wait_tuples = Counter()   # (min,max) for all other range waits
    per_seq_wait_signature = Counter()  # tuple of all wait ranges in a sequence

    swipe_duration_fixed = Counter()   # scalar duration_ms values
    swipe_duration_range = Counter()   # (min,max) tuples
    n_swipes = 0

    counts_by_kind = Counter()

    for path in files:
        rel = os.path.relpath(path, BASE_DIR)
        kind = classify(os.path.basename(path))
        counts_by_kind[kind] += 1

        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception as exc:  # noqa: BLE001 - report any parse/read failure
            parse_failures.append((rel, f"{type(exc).__name__}: {exc}"))
            continue

        if data.get("sequence_version") != 3:
            version_bad.append((rel, data.get("sequence_version")))
        if data.get("author_width") != SCREEN_W:
            width_bad.append((rel, data.get("author_width")))
        if data.get("author_height") != SCREEN_H:
            height_bad.append((rel, data.get("author_height")))

        steps = data.get("steps") or []
        actions_present = set()
        descs = []
        has_back_keyevent = False
        seq_wait_ranges = []
        has_timer_wait = False

        for idx, step in enumerate(steps):
            action = step.get("action")
            params = step.get("params") or {}
            desc = step.get("description") or ""
            actions_present.add(action)
            descs.append(desc.lower())

            if action == "keyevent" and params.get("code") == 4:
                has_back_keyevent = True

            if action == "tap":
                for axis, limit in (("x", SCREEN_W), ("y", SCREEN_H)):
                    val = coord_value(params.get(axis))
                    if val is None or not (0 <= val <= limit):
                        coord_oob.append((rel, idx, f"tap {axis}={val!r} (limit {limit})"))

            elif action == "swipe":
                for axis, limit in (("x1", SCREEN_W), ("x2", SCREEN_W),
                                    ("y1", SCREEN_H), ("y2", SCREEN_H)):
                    val = coord_value(params.get(axis))
                    if val is None or not (0 <= val <= limit):
                        coord_oob.append((rel, idx, f"swipe {axis}={val!r} (limit {limit})"))
                n_swipes += 1
                dur = params.get("duration_ms")
                if isinstance(dur, dict):
                    swipe_duration_range[(dur.get("min"), dur.get("max"))] += 1
                elif isinstance(dur, (int, float)):
                    swipe_duration_fixed[dur] += 1

            elif action == "wait":
                n_wait_steps += 1
                sec = params.get("seconds")
                if isinstance(sec, dict):
                    mn, mx = sec.get("min"), sec.get("max")
                    if isinstance(mn, (int, float)) and isinstance(mx, (int, float)):
                        if mx > mn:
                            n_range_waits += 1
                            seq_wait_ranges.append((mn, mx))
                            if mn >= TIMER_MIN_SECONDS:
                                has_timer_wait = True
                                timer_wait_tuples[(mn, mx)] += 1
                            else:
                                settle_wait_tuples[(mn, mx)] += 1
                        else:
                            min_eq_max_waits.append((rel, idx, f"min={mn} max={mx}"))
                    else:
                        bad_wait_shape.append((rel, idx, repr(sec)))
                elif isinstance(sec, (int, float)):
                    fixed_scalar_waits.append((rel, idx, sec))
                else:
                    bad_wait_shape.append((rel, idx, repr(sec)))

        per_seq_wait_signature[tuple(seq_wait_ranges)] += 1

        # Required structure checks
        missing = [a for a in REQUIRED_ACTIONS if a not in actions_present]
        all_desc = " | ".join(descs)
        if "yes, i am 21" not in all_desc and "age gate" not in all_desc:
            missing.append("age-gate tap (description)")
        if "start perfect dab" not in all_desc:
            missing.append("Start Perfect Dab tap (description)")
        if kind == "ad":
            if "tap ad" not in all_desc:
                missing.append("ad tap ('Tap ad' description)")
            if not has_back_keyevent:
                missing.append("back keyevent (code 4)")
        if missing:
            missing_required.append((rel, missing))

        if kind == "complete" and not has_timer_wait:
            timer_missing.append(rel)

    # ---------- report ----------
    lines = []
    out = lines.append

    def status(fail_count):
        return "PASS" if fail_count == 0 else f"FAIL ({fail_count})"

    def examples(items, fmt=str):
        for item in items[:MAX_EXAMPLES]:
            out(f"    - {fmt(item)}")
        if len(items) > MAX_EXAMPLES:
            out(f"    ... and {len(items) - MAX_EXAMPLES} more")

    out("=" * 72)
    out("SEQUENCE STRUCTURE AUDIT")
    out(f"Scanned: {BASE_DIR} (excluding: {', '.join(sorted(EXCLUDE_DIRS))})")
    out(f"Files scanned: {len(files)}  "
        f"(complete={counts_by_kind['complete']}, ad={counts_by_kind['ad']}, "
        f"halfway={counts_by_kind['halfway']}, other={counts_by_kind['other']})")
    out("=" * 72)
    out("")
    out("SUMMARY")
    out(f"  1. JSON validity ............................ {status(len(parse_failures))}")
    out(f"  2. sequence_version == 3 .................... {status(len(version_bad))}")
    out(f"     author_width == 900 ...................... {status(len(width_bad))}")
    out(f"     author_height == 1600 .................... {status(len(height_bad))}")
    out(f"  3. required structure (actions/desc) ........ {status(len(missing_required))}")
    out(f"  4. coordinate bounds (0..900 x 0..1600) ..... {status(len(coord_oob))}")
    out(f"  5. complete-seq timer wait >= {TIMER_MIN_SECONDS:.0f}s .......... {status(len(timer_missing))}")
    n_bad_waits = len(fixed_scalar_waits) + len(min_eq_max_waits) + len(bad_wait_shape)
    out(f"  6. wait humanization (range, max>min) ....... {status(n_bad_waits)}")
    out(f"  7. swipe duration variance .................. "
        f"INFO (fixed={sum(swipe_duration_fixed.values())}, "
        f"range={sum(swipe_duration_range.values())} of {n_swipes} swipes)")
    out("")

    out("-" * 72)
    out("1. JSON VALIDITY")
    out(f"  Parse failures: {len(parse_failures)}")
    examples(parse_failures, lambda t: f"{t[0]}: {t[1]}")
    out("")

    out("-" * 72)
    out("2. VERSION / AUTHOR DIMENSIONS")
    out(f"  sequence_version != 3: {len(version_bad)}")
    examples(version_bad, lambda t: f"{t[0]} (got {t[1]!r})")
    out(f"  author_width != 900: {len(width_bad)}")
    examples(width_bad, lambda t: f"{t[0]} (got {t[1]!r})")
    out(f"  author_height != 1600: {len(height_bad)}")
    examples(height_bad, lambda t: f"{t[0]} (got {t[1]!r})")
    out("")

    out("-" * 72)
    out("3. REQUIRED STRUCTURE")
    out(f"  Sequences with missing required steps: {len(missing_required)}")
    miss_counter = Counter()
    for _, miss in missing_required:
        miss_counter.update(miss)
    for what, cnt in miss_counter.most_common():
        out(f"    missing '{what}': {cnt} sequence(s)")
    examples(missing_required, lambda t: f"{t[0]}: missing {', '.join(t[1])}")
    out("")

    out("-" * 72)
    out("4. COORDINATE BOUNDS")
    out(f"  Out-of-bounds coordinates: {len(coord_oob)}")
    examples(coord_oob, lambda t: f"{t[0]} step {t[1]}: {t[2]}")
    out("")

    out("-" * 72)
    out("5. TIMER WAIT (complete sequences)")
    out(f"  Complete sequences missing a wait with min >= {TIMER_MIN_SECONDS:.0f}s: "
        f"{len(timer_missing)} of {counts_by_kind['complete']}")
    examples(timer_missing)
    out("")

    out("-" * 72)
    out("6. HUMANIZATION / TIMING VARIANCE (waits)")
    out(f"  Total wait steps: {n_wait_steps}")
    out(f"  Proper {{min,max}} ranges (max > min): {n_range_waits}")
    out(f"  Fixed scalar waits: {len(fixed_scalar_waits)}")
    examples(fixed_scalar_waits, lambda t: f"{t[0]} step {t[1]}: seconds={t[2]}")
    out(f"  Ranges with min == max: {len(min_eq_max_waits)}")
    examples(min_eq_max_waits, lambda t: f"{t[0]} step {t[1]}: {t[2]}")
    out(f"  Malformed seconds values: {len(bad_wait_shape)}")
    examples(bad_wait_shape, lambda t: f"{t[0]} step {t[1]}: {t[2]}")
    out("")
    out(f"  Distinct (min,max) tuples for TIMER waits (min >= {TIMER_MIN_SECONDS:.0f}s): "
        f"{len(timer_wait_tuples)}")
    for (mn, mx), cnt in sorted(timer_wait_tuples.items())[:MAX_EXAMPLES]:
        out(f"    ({mn}, {mx}): {cnt} occurrence(s)")
    if len(timer_wait_tuples) > MAX_EXAMPLES:
        out(f"    ... and {len(timer_wait_tuples) - MAX_EXAMPLES} more tuples")
    out(f"  Distinct (min,max) tuples for SETTLE/other waits: {len(settle_wait_tuples)}")
    top_settle = settle_wait_tuples.most_common(10)
    for (mn, mx), cnt in top_settle:
        out(f"    ({mn}, {mx}): {cnt} occurrence(s)")
    if len(settle_wait_tuples) > 10:
        out(f"    ... and {len(settle_wait_tuples) - 10} more tuples")
    out(f"  Distinct per-sequence wait signatures: {len(per_seq_wait_signature)} "
        f"across {sum(per_seq_wait_signature.values())} sequences")
    most_common_sig_count = per_seq_wait_signature.most_common(1)[0][1] if per_seq_wait_signature else 0
    out(f"    (largest group of sequences sharing an identical wait signature: "
        f"{most_common_sig_count})")
    out("")

    out("-" * 72)
    out("7. SWIPE / SCROLL DURATION VARIANCE")
    out(f"  Total swipe steps: {n_swipes}")
    out(f"  Fixed scalar duration_ms: {sum(swipe_duration_fixed.values())} "
        f"({len(swipe_duration_fixed)} distinct values)")
    if swipe_duration_fixed:
        vals = sorted(swipe_duration_fixed)
        out(f"    fixed value range: {vals[0]} .. {vals[-1]} ms")
        for v, cnt in swipe_duration_fixed.most_common(10):
            out(f"    {v} ms: {cnt} occurrence(s)")
        if len(swipe_duration_fixed) > 10:
            out(f"    ... and {len(swipe_duration_fixed) - 10} more distinct values")
    out(f"  Range duration_ms: {sum(swipe_duration_range.values())} "
        f"({len(swipe_duration_range)} distinct (min,max) tuples)")
    for (mn, mx), cnt in sorted(swipe_duration_range.items())[:MAX_EXAMPLES]:
        out(f"    ({mn}, {mx}) ms: {cnt} occurrence(s)")
    if len(swipe_duration_range) > MAX_EXAMPLES:
        out(f"    ... and {len(swipe_duration_range) - MAX_EXAMPLES} more tuples")
    out("")
    out("=" * 72)
    overall_fail = (len(parse_failures) + len(version_bad) + len(width_bad)
                    + len(height_bad) + len(missing_required) + len(coord_oob)
                    + len(timer_missing) + n_bad_waits)
    out(f"OVERALL: {'PASS' if overall_fail == 0 else f'FAIL ({overall_fail} total violations)'}")
    out("=" * 72)

    report = "\n".join(lines)
    print(report)

    os.makedirs(os.path.dirname(REPORT_PATH), exist_ok=True)
    with open(REPORT_PATH, "w", encoding="utf-8") as fh:
        fh.write(report + "\n")
    print(f"\nFull report written to: {REPORT_PATH}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
