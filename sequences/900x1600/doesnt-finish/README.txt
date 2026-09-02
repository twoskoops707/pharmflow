Doesn't-finish DabFlow sequences (900x1600)
============================================

These JSON flows start the dab timer but do NOT run it to completion.

After funnel (age + material/concentrate/heater picks), scroll, and Start Dab,
the sequence waits only heat + (cool_down / 2) seconds, then closes the browser
(com.android.browser). That exits roughly halfway through the cool-down phase.

They omit: completion animation wait, skip-session popup, Stats tab, scroll,
rotate_identity, and full_reset.

Use the full no-ad matrix under sequences/900x1600/no-ad/ when you need a
completed session with identity tail.

Filenames: dabflow__doesnt_finish__mat-{material}__conc-{concentrate}__heat-{heater}.json
