# Installation pattern (all CMx remote APIs)

Every service that uses **`cmx-remote-access`** should ship a root-level **`install.ps1`** that:

1. **Dot-sources** `scripts/CmxInstallCore.ps1` from this package (path relative to the CellMax monorepo).
2. Calls **`Find-CellMaxMonorepoRoot`** to ensure the checkout includes `interfaces/cmx-remote-access` and sibling packages (`packages/file-converter`, etc.).
3. Runs **`Test-CmxPython`**, **`Test-CmxGit`**, **`Test-CmxPoetry`** (with optional winget / Poetry bootstrap when the operator agrees).
4. Runs **`Invoke-CmxPoetryInstall`** for that service’s directory (or `pip install -e .` if you later publish wheels only).
5. Calls **`Write-CmxManualDependencyWarning`** for anything that cannot be scripted (vendor COM, lab hardware, licenses).

6. **Optional:** interactive **`.env` creation** using shared prompt helpers from `CmxInstallCore.ps1` so operators enter explicit `SERVICE_API_TOKEN`, optional `ADMIN_API_TOKEN`, bind address, etc., without manual editing.
7. Each installation stores its own local tokens for now. Keep auth protocol shared; upgrade storage later if needed.

This keeps the **same prompts, colors, and prerequisite checks** across `active-cell-api`, `pdm-api`, and future gateways.

## Monorepo layout required for path dependencies

```
cellmaxtechnologies/
  interfaces/cmx-remote-access/packages/cmx-remote-access/
  packages/active-cell-api/
  packages/file-converter/
```

Clone or sync the whole tree; do not copy a single folder unless you switch to published packages on PyPI.
