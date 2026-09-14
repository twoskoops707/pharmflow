# DabFlow live site audit (getdabflow.app)

Audited: 2026-07-04 via `automation/audit_dabflow_live.py` against public assets.

**Source repo (not in CPharm):** `C:\Users\jsmil\StudioProjects\DabFlow`, branch **`web`** / **`www`**, deployed to **Cloudflare Pages** at `https://getdabflow.app`.

## What is deployed correctly

| Check | Status |
|-------|--------|
| Cloudflare Pages | `server: cloudflare`, Pages Analytics beacon present |
| Mantis loader | `mantodea.min.js` + `recommend.min.js` from `assets.mantisadnetwork.com` |
| Mantis property | `6950d5527c56c6494f189e46` in HTML shell |
| Ad containers | 15× `#ad-slot-N` with matching `data-mantis-zone="zone-*"` |
| Timer/cool slot DOM | `#cooldown-video-ad` present on `#timer-screen` |
| Recent deploy | `Last-Modified` on assets updates on push (checked 2026-07-04) |

## Bugs blocking ads on some tabs (fix in DabFlow `www/js/app.js`)

### 1. `screenZoneMap` zone name typos

Live `app.js` refreshes **wrong** zone ids (trailing `-`) that do not exist in HTML:

```javascript
// BROKEN (live)
timer:    ['zone-two', 'zone-three', 'zone-four-'],
glass:    ['zone-eight-', 'zone-nine', 'zone-ten-', 'zone-eleven-'],
settings: ['zone-twelve-', 'zone-thirteen-', 'zone-fourteen-', 'zone-fifteen-']
```

HTML uses `zone-four`, `zone-eight`, `zone-ten`, etc. **without** trailing dashes.

**Fix:**

```javascript
const screenZoneMap = {
    home:     ['zone-one', 'tester'],
    timer:    ['zone-two', 'zone-three', 'zone-four'],
    stats:    ['zone-five', 'zone-six', 'zone-seven'],
    glass:    ['zone-eight', 'zone-nine', 'zone-ten', 'zone-eleven'],
    settings: ['zone-twelve', 'zone-thirteen', 'zone-fourteen', 'zone-fifteen']
};
```

After editing, push **`web`** branch → Cloudflare Pages redeploys production.

### 2. Cooldown video ad never shown

`#cooldown-video-ad` is hidden in `startTimer()` and never set `display: block` when heat ends. Only `#ad-slot-2` / `zone-two` below it can fill via initial Mantis load.

**Fix (in `runTimer()` when switching heat → cool):**

```javascript
if (state.timer.mode === 'cool' && !state.settings.isPremium) {
    const videoAd = document.getElementById('cooldown-video-ad');
    if (videoAd) {
        videoAd.style.display = 'block';
        if (!videoAd.querySelector('[data-mantis-zone]')) {
            videoAd.innerHTML = '<div data-mantis-zone="zone-two"></div>';
        }
        if (typeof mantis !== 'undefined') {
            setTimeout(() => mantis.push(['display', 'refresh', 'zone-two']), 300);
        }
    }
}
```

(Adjust zone if Mantis dashboard uses a dedicated video zone.)

### 3. Deployment artifact: `/css/app.css` is HTML

`GET /css/app.css` returns `text/html` (full index document, ~119 KB). The app does **not** link this file (uses `design-system.css`, `components.css`, …). Remove duplicate `index.html` from `www/css/app.css` on deploy or fix Pages build output directory.

### 4. Cloudflare bot fight on `/`

Automated `curl`/headless gets **403** + `cf-mitigated: challenge` on `/` and `/index.html`. Real browsers and MuMu WebView pass after challenge. Tor exits may see low Mantis fill — expected. **Default MuMu ad runs use Scramble mode** (direct internet + rotated device fingerprint per session; set in Go → section F or ``desktop_prefs.json`` ``browse_proxy_mode``).

### Browse proxy modes (CPharm)

| Mode | Use when |
|------|----------|
| **scramble** (default) | MuMu ad farming — Mantis fill + new device look each visit |
| **direct** | Home IP, no identity rotation |
| **upstream** | Per-phone residential proxy in ``phone_upstream_proxies`` |
| **tor** | Privacy / geo diversity — ads often empty on emulator |

## CPharm runtime compensation (until deploy)

CPharm injects ``automation/dabflow_mantis_client_patch.py`` via Chrome DevTools after each
``open_url`` to getdabflow.app (default **ON**; ``desktop_prefs.json`` → ``dabflow_mantis_patch``).

This fixes zone refresh + cooldown video **in the browser** without waiting for Cloudflare deploy.

Generate a deploy-ready ``app.js``: ``python3 tools/patch_dabflow_appjs_for_deploy.py`` → ``dabflow-fix/``.

## CPharm automation alignment

Ad-path sequences tap:

| Checkpoint | DOM | Baseline tap |
|------------|-----|--------------|
| `ad_home` | `#ad-slot-1` / zone-one | (450, 964) |
| `ad_timer_video` | `#cooldown-video-ad` (needs fix #2 above) | (450, 875) |
| `ad_timer_banner` | `#ad-slot-2` / zone-two | (450, 1000) |
| `ad_glass` | `#ad-slot-8` / zone-eight | (450, 1100) |
| `ad_stats` | stats `.ad-container` / zone-five band | (450, 857) |
| `ad_settings` | `#ad-slot-12` / zone-twelve | (450, 1180) |

Run audit locally:

```bash
python3 automation/audit_dabflow_live.py
```

## Cloudflare deploy checklist (operator)

1. In **DabFlow** repo: commit fixes on **`web`** (or whichever branch Pages production tracks).
2. Cloudflare dashboard → **Workers & Pages** → DabFlow project → confirm **Production branch** = `web`.
3. Push → wait for green deployment → hard-refresh `https://getdabflow.app` on phone.
4. Re-run `python3 automation/audit_dabflow_live.py` until **OK**.
5. On farm PC: **PharmFlow → Phones → Set up my phones** to sync sequences + `groups_config.json`.
