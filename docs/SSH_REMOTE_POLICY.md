## SSH Remote Policy

This repository uses SSH Git remotes only.

Required `origin` URL format:

`git@github.com:twoskoops707/cpharm.git`

Quick check:

`git remote -v`

If your remote is HTTPS, switch it:

`git remote set-url origin git@github.com:twoskoops707/cpharm.git`

Why: SSH remotes are required for consistent auth, automation, and least-friction private repo access.
