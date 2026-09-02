# Wizard UI/UX Modernization — 2026-06-21

## Summary

Modernized scroll behavior, theme parity, and inline guidance across the CPharm setup wizard and automation dashboard. Work completes prerequisite task **3ecea01b**.

## Scroll fixes (all wizard surfaces)

| Surface | Change |
|---------|--------|
| **PerPhoneSequenceEditor** | Outer canvas uses `fill="x"` (not `expand=True`) so `create_window` content is not clipped; playlist pane scrolls independently; `_refresh_per_phone_scrollregions()` after layout changes |
| **AddStepDialog** | Full scroll canvas + fixed footer (OK/Cancel outside scroll); fields card no longer nested double-scroll |
| **Sequence generator page** | Footer actions stay outside scroll canvas (existing tests: `test_sequence_footer_visibility.py`) |
| **GroupsPage / wizard shell** | Nested canvas mousewheel routing prefers canvas under pointer |
| **Welcome / Prerequisites / Boot** | Log/status panels use `fill="x"` so main page scroll remains usable |

## Theme (`wizard/wizard_theme.py`)

- Violet/slate palette (BG `#0f1219`, accent `#9b8cf8`) — distinct from legacy teal cycles
- `themed_vertical_scrollbar` + `_style_scrollbars` (clam ttk) for readable dark trough on Windows
- `instruction_card`, `operator_callout`, responsive `wraplength` helpers
- Footer dock styling (`FOOTER_BG`, accent dividers)

## Dashboard (`automation/dashboard.html`)

- Design tokens aligned with wizard: `--g` green accent, dark `--bg0`–`--bg3`, Syne/IBM Plex Mono/DM Sans
- Custom scrollbar colors (`--scroll-thumb`) for dark chrome parity
- Sticky header with backdrop blur; card-based phone status grid

## Inline help added/updated

- Playlist card: folder mode explanation + Set A/B guidance
- AddStepDialog: per-step-type tips (open_url post-wait, tap jitter, etc.)
- Sequence editor: “Where are my steps?” scroll hint; profile mismatch warning
- ATT/tracking quick helper on per-phone editor

## Verification

```text
py -3 -m py_compile wizard/setup_wizard.py wizard/wizard_theme.py wizard/sequence_humanize.py
```

Tk layout smoke (optional): `py -3 wizard/test_sequence_footer_visibility.py`

## Files touched

- `wizard/setup_wizard.py` — scroll, AddStepDialog, playlist/folder UI
- `wizard/wizard_theme.py` — tokens, scrollbars, cards
- `automation/dashboard.html` — CSS tokens / scrollbar styling
- `wizard/sequence_humanize.py` — preserve `timer_complete` wait (no humanize spread)
