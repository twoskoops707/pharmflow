"""

Authoring baseline 900×1600 tap centers for DabFlow ``origin/web`` (getdabflow.app).



Source repo: ``C:\\Users\\jsmil\\StudioProjects\\DabFlow`` branch ``origin/web``

commit ``dd22fff2cb484a581d703321651be7f0d6b04c55``.

Coordinates measured via Playwright at 900×1600 against live getdabflow.app

(``measure_dabflow_coords.py``) and cross-checked against DOM selectors in

``www/index.html`` + ``www/css/components.css`` (``.nav-bar`` height 70px,

``.screen`` padding ``var(--space-5)`` = 24px).



Each interactive region is ``(cx, cy, half_w, half_h)`` in baseline pixels for

clamping humanization offsets while staying inside safe hit targets.

"""



from __future__ import annotations



from typing import NamedTuple



BW = 900

BH = 1600





class Region(NamedTuple):

    cx: int

    cy: int

    half_w: int

    half_h: int





# Bottom nav — www/index.html:.nav-bar a.nav-item[data-screen]; www/css/components.css:.nav-bar

NAV_Y = 1566  # Playwright getBoundingClientRect cy @ 900×1600
NAV_Y_MUMU_PAGE = 1374  # JSON page y: NAV_Y − wv_top(~192); execute_steps adds wv_top → screen 1566

NAV_HOME_X = 90       # www/index.html:[data-screen="home"].nav-item

NAV_TIMER_X = 270     # www/index.html:[data-screen="timer"].nav-item

NAV_STATS_X = 450     # www/index.html:[data-screen="stats"].nav-item

NAV_GLASS_X = 630     # www/index.html:[data-screen="glass"].nav-item

NAV_SETTINGS_X = 810  # www/index.html:[data-screen="settings"].nav-item





def nav_x(screen: str) -> int:

    return {

        "home": NAV_HOME_X,

        "timer": NAV_TIMER_X,

        "stats": NAV_STATS_X,

        "glass": NAV_GLASS_X,

        "settings": NAV_SETTINGS_X,

    }[screen]





def nav_region(screen: str) -> Region:

    return Region(nav_x(screen), NAV_Y, 72, 28)


# Aliases for bottom-nav demo tail (Skip → tab → scroll; no close_app)
# TAB_* cy=NAV_Y (1566 Playwright); JSON tap uses bottom_nav:true → screen y=NAV_Y (no wv_top)
TAB_STATS = Region(NAV_STATS_X, NAV_Y, 72, 28)
TAB_GLASS = Region(NAV_GLASS_X, NAV_Y, 72, 28)
TAB_SETTINGS = Region(NAV_SETTINGS_X, NAV_Y, 72, 28)






# Age gate — www/index.html:#age-yes-btn (LEFT column in 1fr 1fr grid)

# half_w kept tight — gap to #age-no-btn starts ~445; jitter must not reach No.

AGE_YES = Region(359, 912, 50, 30)  # www/index.html:#age-yes-btn Playwright
AGE_YES_MUMU = Region(460, 907, 50, 30)  # MuMu USER_TAP_ANALYSIS validated
# At runtime dashboard/wizard add webview_content_top_inset (MuMu stock browser ~192px @ 900x1600).

AGE_NO = Region(541, 912, 50, 30)   # www/index.html:#age-no-btn (reference only)

# Target: loaded → Yes tap ≤ ~3s on MuMu (nobody reads the page).
AGE_GATE_OPEN_POST_WAIT_MAX_SEC = 1.25
AGE_GATE_PRE_WAIT_MAX_MS = 120.0
AGE_GATE_POST_TAP_WAIT_SEC = 0.18


def age_gate_page_bounds() -> tuple[int, int, int, int]:
    """Union bbox for Yes button (Playwright + MuMu) in page coords @ 900×1600."""
    regions = (AGE_YES, AGE_YES_MUMU)
    min_x = min(r.cx - r.half_w for r in regions)
    max_x = max(r.cx + r.half_w for r in regions)
    min_y = min(r.cy - r.half_h for r in regions)
    max_y = max(r.cy + r.half_h for r in regions)
    return min_x, max_x, min_y, max_y


def age_gate_tap_page_coords() -> tuple[int, int]:
    """MuMu-validated #age-yes-btn center (use for all farm runs)."""
    return AGE_YES_MUMU.cx, AGE_YES_MUMU.cy


def age_gate_tap_step() -> dict:
    """Canonical fast age-gate step for sequence authors."""
    cx, cy = age_gate_tap_page_coords()
    return {
        "type": "tap",
        "x": cx,
        "y": cy,
        "base_w": 900,
        "base_h": 1600,
        "retries": 5,
        "jitter": 4,
        "pre_wait_ms": 80,
        "age_verification": True,
        "checkpoint": "age_verification",
        "phase": "pre_site_fast",
    }


# Material row — www/index.html:.option-grid [data-setting="material"]

MAT_POS = {

    "quartz": Region(163, 445, 115, 22),    # www/index.html:[data-setting="material"][data-value="quartz"]

    "titanium": Region(450, 445, 115, 22),  # www/index.html:[data-setting="material"][data-value="titanium"]

    "ceramic": Region(737, 445, 115, 22),   # www/index.html:[data-setting="material"][data-value="ceramic"]
}

# MuMu WebView validated page coords (USER_TAP_ANALYSIS 2026-06-19) — differ from Playwright centers
MAT_POS_MUMU = {
    "quartz": Region(163, 501, 80, 25),
    "titanium": Region(450, 501, 80, 25),
    "ceramic": Region(660, 501, 80, 25),
}

CONC_POS_MUMU = {
    "shatter": Region(81, 587, 50, 22),
    "wax": Region(204, 587, 50, 22),
    "live-resin": Region(327, 587, 50, 22),
    "rosin": Region(450, 587, 50, 22),
    "diamonds": Region(573, 587, 50, 22),
    "crumble": Region(696, 587, 50, 22),
    "budder": Region(819, 587, 50, 22),
    "sauce": Region(81, 644, 50, 22),
    "hash-rosin": Region(204, 644, 50, 22),
    "distillate": Region(366, 587, 50, 22),
}

HEAT_POS_MUMU = {
    "butane": Region(235, 663, 120, 22),
    "propane": Region(593, 663, 120, 22),
}



# Concentrate grid — www/index.html:.option-grid auto-fit minmax(100px,1fr); 7+3 at 900px

CONC_POS = {

    "shatter": Region(81, 535, 50, 22),     # www/index.html:[data-setting="concentrate"][data-value="shatter"]

    "wax": Region(204, 535, 50, 22),        # www/index.html:[data-setting="concentrate"][data-value="wax"]

    "live-resin": Region(327, 535, 50, 22), # www/index.html:[data-setting="concentrate"][data-value="live-resin"]

    "rosin": Region(450, 535, 50, 22),      # www/index.html:[data-setting="concentrate"][data-value="rosin"]

    "diamonds": Region(573, 535, 50, 22),   # www/index.html:[data-setting="concentrate"][data-value="diamonds"]

    "crumble": Region(696, 535, 50, 22),    # www/index.html:[data-setting="concentrate"][data-value="crumble"]

    "budder": Region(819, 535, 50, 22),     # www/index.html:[data-setting="concentrate"][data-value="budder"]

    "sauce": Region(81, 592, 50, 22),       # www/index.html:[data-setting="concentrate"][data-value="sauce"]

    "hash-rosin": Region(204, 592, 50, 22),  # www/index.html:[data-setting="concentrate"][data-value="hash-rosin"]

    "distillate": Region(327, 592, 50, 22), # www/index.html:[data-setting="concentrate"][data-value="distillate"]

}



CONC_ORDER = tuple(CONC_POS.keys())





def concentrate_region_mumu(key: str) -> Region:
    try:
        return CONC_POS_MUMU[key]
    except KeyError as e:
        raise KeyError(key) from e


def concentrate_region(key: str) -> Region:

    try:

        return CONC_POS[key]

    except KeyError as e:

        raise KeyError(key) from e





# Heater row — www/index.html:.option-grid [data-setting="heater"] (2-col at 900px)

HEAT_POS = {

    "butane": Region(235, 682, 200, 22),  # www/index.html:[data-setting="heater"][data-value="butane"]

    "propane": Region(665, 682, 200, 22), # www/index.html:[data-setting="heater"][data-value="propane"]

}



# Primary CTA — www/index.html:455 #start-dab-btn
START_DAB_PLAYWRIGHT = Region(450, 1231, 400, 40)  # Playwright getBoundingClientRect @ 900×1600
START_DAB = Region(450, 1075, 200, 35)  # MuMu uia start-dab-btn center page Y post-scroll; screen ~1267 (+192 inset)
START_DAB_AFTER_SCROLL = START_DAB  # alias — tap only AFTER SCROLL_TO_START_DAB_SWIPES

# Scroll home to reveal #start-dab-btn — finger moves UP → page scrolls DOWN (www/index.html:#home-screen main)
# Required on MuMu 900×1600: heater row ~y682, ads ~y964, start btn ~y1231; webview fold ~y1100 without scroll.
SCROLL_TO_START_DAB_SWIPES: tuple[dict[str, int], ...] = (
    {"x1": 450, "y1": 1150, "x2": 450, "y2": 700, "ms": 750},   # pass custom-times + ad slots
    {"x1": 450, "y1": 1200, "x2": 450, "y2": 750, "ms": 700},   # reveal #start-dab-btn cy≈1231
)



# Timer controls — www/index.html:#timer-screen div.flex.gap-4

PAUSE_BTN = Region(84, 767, 55, 25)   # www/index.html:#pause-btn

RESET_BTN = Region(220, 767, 55, 25)  # www/index.html:#reset-btn



# Timer-complete session notes modal — www/index.html:1474 #session-notes-modal
# Skip button www/index.html:1605 onclick="skipSessionNotes()" → app.js skipSessionNotes()
# Playwright getdabflow.app @ 900×1600 (modal forced visible): cx=337 cy=1266 w=121 h=51
# NOT #reset-btn (cx=220 cy=767) — post-timer modal only. JSON uses page Y; execute_steps adds wv_top.
SESSION_NOTES_SKIP = Region(337, 1266, 60, 25)  # Playwright #session-notes-modal Skip @ 900×1600
SESSION_NOTES_SKIP_MUMU = SESSION_NOTES_SKIP  # page coords; execute_steps adds wv_top
# MuMu validated Skip on session-notes modal (demo ONE live proof 2026-06-21)
SESSION_NOTES_SKIP_ONE = Region(276, 984, 60, 25)



# Mantis ad zones — getdabflow.app/css/app.css (origin/web) data-mantis-zone slots

HOME_AD_SLOT = Region(450, 964, 140, 120)  # #ad-slot-1 zone-one @ 900×1600 Playwright

# Timer screen — #cooldown-video-ad (empty until DabFlow app.js shows it on cool)
# then #ad-slot-2 / #ad-slot-3 (zone-two/three). CPharm taps both video slot + zone-two.
TIMER_COOLDOWN_VIDEO_AD = Region(450, 875, 150, 125)  # #cooldown-video-ad below pause/reset
TIMER_AD_SLOT = Region(450, 1000, 140, 120)  # #ad-slot-2 zone-two — primary Mantis fill today
TIMER_AD_SLOT_LOWER = Region(450, 1280, 140, 120)  # #ad-slot-3 zone-three

STATS_AD_SLOT = Region(450, 857, 140, 120)  # #stats-screen .ad-container / zone-five band

GLASS_AD_SLOT = Region(450, 1100, 140, 120)  # #ad-slot-8 zone-eight (after scroll on glass tab)

SETTINGS_AD_SLOT = Region(450, 1180, 140, 120)  # #ad-slot-12 zone-twelve (after scroll on settings)



# Glass Art tab — www/index.html:#glass-screen a[href*="mrgrayglass"]

GLASS_ART_SELECT = Region(247, 323, 180, 70)



# Scroll bands — www/index.html:main (overflow-y:auto)

STATS_SCROLL = Region(450, 800, 400, 600)   # www/index.html:#stats-screen

GLASS_SCROLL = Region(450, 700, 400, 700)   # www/index.html:#glass-screen

# MuMu 900x1600 scroll-to-bottom swipes after tab switch (finger up -> page down)
STATS_SCROLL_BOTTOM_SWIPES: tuple[dict[str, int], ...] = (
    {"x1": 450, "y1": 950, "x2": 450, "y2": 650, "ms": 900},
    {"x1": 450, "y1": 900, "x2": 450, "y2": 550, "ms": 850},
)
GLASS_SCROLL_BOTTOM_SWIPES: tuple[dict[str, int], ...] = (
    {"x1": 450, "y1": 900, "x2": 450, "y2": 600, "ms": 850},
    {"x1": 450, "y1": 850, "x2": 450, "y2": 500, "ms": 800},
)
SETTINGS_SCROLL_BOTTOM_SWIPES: tuple[dict[str, int], ...] = (
    {"x1": 450, "y1": 950, "x2": 450, "y2": 650, "ms": 900},
    {"x1": 450, "y1": 900, "x2": 450, "y2": 550, "ms": 850},
    {"x1": 450, "y1": 850, "x2": 450, "y2": 450, "ms": 800},
)



def scroll_bottom_swipes(screen: str) -> tuple[dict[str, int], ...]:
    if screen == "glass":
        return GLASS_SCROLL_BOTTOM_SWIPES
    if screen == "settings":
        return SETTINGS_SCROLL_BOTTOM_SWIPES
    return STATS_SCROLL_BOTTOM_SWIPES


HOME_SCROLL = Region(450, 600, 400, 900)    # www/index.html:#home-screen





def clamp_to_region(r: Region, x: int, y: int) -> tuple[int, int]:

    if r.half_w <= 0 or r.half_h <= 0:

        return x, y

    nx = min(r.cx + r.half_w, max(r.cx - r.half_w, x))

    ny = min(r.cy + r.half_h, max(r.cy - r.half_h, y))

    return nx, ny





def jitter_point(r: Region, rng, spread: int | None = None) -> tuple[int, int]:

    """Random offset inside region (uniform)."""

    sp = spread if spread is not None else min(r.half_w, r.half_h, 24)

    dx = rng.randint(-sp, sp)

    dy = rng.randint(-sp, sp)

    return clamp_to_region(r, r.cx + dx, r.cy + dy)


