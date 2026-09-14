# Sequence push-only release path (no PR)

This is the concrete path for shipping sequence changes by push only, using `c:\Users\jsmil\source\repos\cpharm` as the git source of truth (because `c:\Users\jsmil\CPharm\cpharm-clone` is not a git working tree in this environment).

## 1) What to commit for sequence changes

Commit the sequence payload and any coupled logic/docs in the same logical change:

- `automation/recordings/sequences/*.json` (changed sequence files)
- `automation/sequence_geometry.py` (if coordinate/normalization logic changed)
- `docs/SEQUENCE_CATALOG.md` and related docs (if behavior docs changed)
- `.github/workflows/build-wizard.yml` **if CI trigger behavior must change with this sequence ship**

Current observed dirty set in `c:\Users\jsmil\source\repos\cpharm` is sequence-heavy plus `automation/sequence_geometry.py`, so the default commit should include those files together.

## 2) What currently triggers on push

From `c:\Users\jsmil\source\repos\cpharm\.github\workflows\build-wizard.yml`:

- Trigger: `on.push.paths: ['wizard/**']` and `workflow_dispatch`
- Meaning: **sequence-only pushes do not auto-run** this workflow.
- Manual path still exists: `workflow_dispatch` can run the build without PR.

From `c:\Users\jsmil\CPharm\cpharm-clone\.github\workflows\build-wizard.yml` (reference mirror):

- Trigger: `on.push` (no path filter) + `workflow_dispatch`
- Meaning: any push would run verify/build/release there.

## 3) Artifact and release expectations

In the tracked repo (`source\repos\cpharm`) the workflow builds and publishes:

- PyInstaller output: `wizard/dist/PharmFlow.exe`
- Actions artifact: `CPharm-exe` (retention 30 days)
- GitHub Release on push/manual run:
  - tag: `wizard-${{ github.run_number }}`
  - release name: `CPharm (build ${{ github.run_number }})`
  - attached asset: `PharmFlow.exe`

Policy expectation: Releases are the primary download path; artifact is fallback/debug evidence.

## 4) Push-only execution path (no PR)

Run in `c:\Users\jsmil\source\repos\cpharm`:

1. Review staged scope:
   - `git status`
2. Stage sequence-related changes:
   - `git add automation/recordings/sequences automation/sequence_geometry.py docs/SEQUENCE_CATALOG.md`
   - Add workflow file too if you are intentionally changing triggers: `git add .github/workflows/build-wizard.yml`
3. Commit:
   - `git commit -m "update sequence bundles and timing geometry for latest dabflow runs"`
4. Push to tracked branch (push-only, no PR flow):
   - `git push origin main`

## 5) Required verify-before-success commands

Do not claim "done", "build exists", or "shipped" until all checks below are run and interpreted:

1. **Working tree check**
   - `git status`
   - Expect: no uncommitted shipping/workflow changes left behind unintentionally.

2. **Branch exists on origin (push really happened)**
   - `git branch -r | rg "origin/main"`
   - and/or `git ls-remote --heads origin main`
   - Expect: remote head resolves for the target branch.

3. **Workflow/release status check**
   - `gh run list --workflow "Build CPharm (.exe)" --branch main --limit 5`
   - If run exists, inspect latest:
     - `gh run view <run-id> --json status,conclusion,url`
   - Check releases:
     - `gh release list --limit 5`
     - `gh release view <tag> --json url,assets`

4. **Success criteria**
   - If workflow ran and passed: latest run conclusion is `success` and release has `PharmFlow.exe`.
   - If workflow did not run for a sequence-only push: report that explicitly as expected due to `paths: ['wizard/**']`, then either:
     - run manual dispatch (`gh workflow run "Build CPharm (.exe)"`), or
     - ship a workflow trigger update in same logical change.
   - If workflow failed: report failing run URL and failure reason; do not claim release exists.

## 6) Practical decision for sequence-only pushes right now

Because current tracked workflow only auto-triggers on `wizard/**`, a pure sequence commit will not produce a new release automatically.

Concrete push-only options:

- **Option A (minimal):** Push sequence commit, then manually dispatch workflow (`workflow_dispatch`) and verify release asset.
- **Option B (structural fix):** In same logical change, update workflow push paths to include sequence/docs/automation files that should trigger a rebuild, then push once and verify.

Either option remains push-only and PR-free.
