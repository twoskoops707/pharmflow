# Emulator and screen size — simple reference

How PharmFlow matches taps to your phone screen.

---

## Pick one screen size and keep it

| Size | Good for |
|------|----------|
| **900 × 1600** | **Default** — shipped getdabflow JSON uses this |
| **1080 × 1920** | Larger phone — also fine |
| **720 × 1280** | Only if you must save RAM |
| **540 × 960** | Too small for reliable web taps |

After you change MuMu display settings, boot the phone and confirm size in the wizard **Groups** editor (mismatch warning).

---

## MuMu on your PC

- **ARM / Snapdragon PC** → install **MuMu for Windows ARM**
- **Regular PC** → install the normal x64 MuMu
- Create phones in **Multi-instance** — clone **after** the first phone works
- **Model = Phone**, not Pad/Tablet
- **Portrait**, **900×1600** for this repo

---

## Developer options (every phone)

1. **Settings → About phone → Build number** — tap **7 times**.
2. **Settings → System → Developer options**
3. Turn **USB debugging** **ON**.

Without USB debugging, PharmFlow cannot control the phone.

---

## Natural timing

On **Launch**, leave human-like timing **on** unless you have a reason to turn it off. Waits and taps vary slightly each run.

---

## Playlists (Set A + Set B)

In **Groups → Edit**:

- **Set A** — main sequence files
- **Set B** — optional; runs after Set A in the same run
- **Mode** — ordered / random / series
- **Shuffle** — optional mix-up each repeat

Empty playlists → PharmFlow uses **inline backup steps**.

---

## Sequence builder (Generator step)

1. Choose **Website** or **App** (or load existing JSON).
2. Fill in URL or package → **Continue →**.
3. Add actions → **Save** to `automation/recordings/sequences/`.
4. Assign files in **Groups → Edit**.

**WebPE** is not a wizard tab anymore — use **Sequence builder** or edit JSON by hand.

---

## Privacy note

Tor, identity reset, and playlists reduce repetition. They do not guarantee anonymity.
