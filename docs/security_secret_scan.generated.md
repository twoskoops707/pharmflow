# Secret Exposure Scan (generated)

Date: 2026-05-06
Repository: `pharmflow`

## Scope and evidence
- Scanned working tree for high-confidence secret signatures (API keys, tokens, private key headers, credential-style assignments).
- Scanned keyword hotspots (`password`, `token`, `secret`, `api_key`, `client_secret`) and manually reviewed returned candidates.
- Scanned git history (`git rev-list --all` + `git grep`) for high-confidence leaked secret signatures.
- Checked sensitive filename patterns (`.env*`, `*.pem`, `*.key`, `*.p12`, `*.pfx`, `*.jks`, `*.kubeconfig`).

## Findings
- High/Critical: 0
- Medium: 0
- Low: 0
- Informational: 1
  - `.gitignore` was missing several sensitive-file patterns.

## Fixed immediately
- Expanded `.gitignore` protections:
  - Added `.env.*` with explicit allowlist for template files (`!.env.example`, `!.env.sample`, `!.env.template`)
  - Added key/certificate patterns (`*.pem`, `*.key`, `*.p12`, `*.pfx`, `*.jks`, `*.kubeconfig`)
  - Added common SSH private key filenames (`id_rsa`, `id_ed25519`)

## Unresolved risks
- No obvious plaintext secrets detected in current tree or high-confidence history scan.
- Residual risk remains for non-patterned secrets (e.g., random opaque values without identifying context).

## Rotate-now checklist
1. No immediate rotation required based on this scan.
2. If any secret was previously shared outside git (chat, logs, screenshots), rotate that credential now.
3. If you later confirm a leaked secret in any commit, rotate first, then remove exposure in code and CI.

## Post-fix rescan result
- Re-scan after `.gitignore` update found no new obvious secret exposures.
