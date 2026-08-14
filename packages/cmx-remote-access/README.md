# cmx-remote-access (Python package)

## Release History

| Version | Date | Notes |
|---|---|---|
| 1.1.4 | 2026-08-14 | Keep credential-backed SMB connections mounted while staging through canonical UNC paths to avoid Windows PowerShell provider path recursion. |
| 1.1.3 | 2026-08-14 | Resolve credential-backed PowerShell drive paths to UNC filesystem paths before hashing staged deployment artifacts. |
| 1.1.2 | 2026-08-04 | Add the DESKTOP-BG8O674 PP API deployment runbook and restart an existing deployment-agent runner during bootstrap upgrades. |
| 1.1.1 | 2026-08-04 | Normalize NSSM local service identities such as `.\ittab` before granting read/execute access to prepared releases. |
| 1.1.0 | 2026-08-04 | Add transport-neutral unattended deployment contracts, a station-side deployment agent, and an SMB publisher with hash validation, health gating, audit results, and rollback. |
| 1.0.2 | 2026-07-26 | Widen tested FastAPI compatibility through 0.140 and refresh the dependency lock. |
| 0.3.15 | 2026-06-01 | Prefer routed physical LAN IPv4 addresses when installers print client URLs. |
| 0.3.14 | 2026-05-29 | Replace existing NSSM services by removing and recreating them instead of editing brittle service parameters in place. |
| 0.3.13 | 2026-05-29 | Clear empty NSSM AppParameters during service updates without failing reinstall flows. |
| 0.3.12 | 2026-05-29 | Show service health wait progress and allow shorter probe timeouts during Windows service installs. |
| 0.3.11 | 2026-05-28 | Make uninstall cleanup configurable so packages can keep or remove install roots explicitly. |
| 0.3.10 | 2026-05-28 | Add shared uninstall-service support for CRA bundles so removal is explicit and consistent. |
| 0.3.9 | 2026-05-28 | Add a shared strict live-service smoke-test helper so CRA-backed APIs use the same URL and token template. |
| 0.3.8 | 2026-05-27 | Validate bundled service installs use Python 3.10 through 3.13 before creating the venv. |
| 0.3.7 | 2026-05-27 | Skip incompatible wheels during bundled installs so one zip can carry wheels for multiple Python versions. |
| 0.3.6 | 2026-05-27 | Upgrade bundled virtualenv pip through python -m pip and install wheel bundles without dependency resolution. |
| 0.3.5 | 2026-05-27 | Generate useful documentation abstracts even when package descriptions are empty. |
| 0.3.4 | 2026-05-26 | Standardize server bundle install wording around install-service.ps1. |
| 0.3.3 | 2026-05-26 | Standardize server bundles around one install-service.ps1 entrypoint. |
| 0.3.2 | 2026-05-26 | Compile README-based PDF documentation for install bundles without shipping LaTeX source. |

Shared **contracts** (`RemoteCommand`, `RemoteResult`) and **FastAPI bearer auth** aligned with `cmx-production-system` services (`SERVICE_API_TOKEN`, `ADMIN_API_TOKEN`, `AUTH_STRICT`).

Install from the monorepo path or publish to your index.

## Environment


| Variable            | Meaning                                                  |
| ------------------- | -------------------------------------------------------- |
| `SERVICE_API_TOKEN` | Bearer token for automation / service clients            |
| `ADMIN_API_TOKEN`   | Optional separate token with role `admin`                |
| `AUTH_STRICT`       | `true` / `1` — reject missing or unknown Bearer with 401 |
Clients may send `Authorization: Bearer …` or `X-App-Token` / `X-API-Key`.

Installers using `cmx-remote-access` should require an explicit `SERVICE_API_TOKEN` when `AUTH_STRICT=true`; they should not silently generate one by default.

## Usage

```python
from cmx_remote_access import load_remote_access_settings, require_roles

settings = load_remote_access_settings()
service_only = require_roles(settings, frozenset({"service", "admin"}))
```

## Installation UX (shared with all CMx APIs)

- `**scripts/CmxInstallCore.ps1**` — shared source-install seam. Owns monorepo discovery, Python/Git/Poetry checks, common `.env` overwrite flow, and auth prompts.
- `**scripts/CmxBuildCore.ps1**` — shared build seam. Owns Poetry bootstrap, PyInstaller bootstrap, wheel-bundle assembly, robust zip creation, and bundling the vendored `tools/nssm.exe`.
- `**scripts/CmxWindowsServiceCore.ps1**` — shared NSSM/service seam. Owns service install/update/remove, firewall helper, health wait, and bundle/repo `nssm.exe` lookup.
- Child CRA repos should keep `install.ps1` and `build.ps1` thin: pass only product-specific prompts, spec names, copied files, and sibling dependency repos.

If shared install/build behavior changes, change CRA once, then update child repos. Child repos should not copy generic CRA logic.

## Unattended service deployment

CRA's unattended deployment protocol separates transport from privileged installation:

- `New-CmxDeploymentAgentBundle.ps1` builds the versioned portable bootstrap ZIP used for the one-time station setup.
- `Publish-CmxServiceRelease.ps1` publishes a versioned bundle and strict manifest to a station inbox over SMB. It writes the ready marker last, waits for the matching result, and verifies the service's reported ID and version.
- `Install-CmxDeploymentAgent.ps1` is a one-time elevated station bootstrap. It creates station-local inbox, result, release, and lock roots and registers the deployment runner.
- `Run-CmxDeploymentAgent.ps1` claims ready deployments into a SYSTEM/Admin-only queue, then processes them locally. It validates the manifest and protected artifact hash, enforces station-local package/service/health/entrypoint profiles, preserves the existing Windows service identity and ProgramData configuration, switches the existing NSSM service to a versioned release, health-checks it, and health-checks any rollback.
- `CmxDeploymentAgentCore.ps1` contains the shared fail-closed validation, locking, release, health, audit-result, and rollback behavior.

Service-account passwords, API tokens, UNC credentials, and `.env` files remain on the station. They must never be included in deployment manifests, bundles, launcher arguments, or SMB staging directories. The agent upgrades existing services only; first installation and agent bootstrap still require one elevated station action.

The machine-specific PP API procedure for the first deployed host is [DESKTOP-BG8O674 active-cell-pp-api](docs/stations/DESKTOP-BG8O674-active-cell-pp-api.md). It records the station topology, commands, secret boundary, verification gates, retry rules, and SSH migration seam without storing credentials.

SMB is the first transport. A later SSH/SFTP publisher should stage the same artifact and manifest and trigger the same station agent rather than duplicate installation logic.

### One-time station bootstrap

Copy the deployment-agent ZIP to the station, open an elevated Windows PowerShell console there, and run:

```powershell
Expand-Archive -LiteralPath .\cmx-deployment-agent-1.1.4.zip -DestinationPath .\cmx-deployment-agent-1.1.4
Set-Location .\cmx-deployment-agent-1.1.4
.\Install-CmxDeploymentAgent.ps1 -DeploymentPrincipal 'STATION\cmx-deployer'
```

Replace `STATION\cmx-deployer` with the dedicated Windows account that the publishing computer will use over SMB. Broad principals such as Everyone, Authenticated Users, Users, and Guests are rejected. The bootstrap discovers NSSM from an existing Windows service when there is one unique NSSM path; otherwise pass `-NssmExe 'C:\path\to\nssm.exe'`.

The bootstrap creates the hidden `CellmaxDeploy$` share and a LocalSystem startup task. The deployment principal can modify only `inbox` and read `results`; agent scripts, the protected claim queue, release files, locks, and service credentials remain unavailable through the share. A prepared release grants the unchanged service identity read/execute access only. The default station-local allowlist pins both known services: PP API on port 8765 and AC API on port 8766. A manifest cannot redirect the agent to another Windows service or executable path.

### Publish PP API 0.3.23 over SMB

From the publishing computer, use a credential prompt so the SMB password is not placed in shell history:

```powershell
$stationCredential = Get-Credential 'STATION\cmx-deployer'

.\Publish-CmxServiceRelease.ps1 `
    -ComputerName '192.168.20.25' `
    -ShareName 'CellmaxDeploy$' `
    -PackageName 'active-cell-pp-api' `
    -PackageVersion '0.3.23' `
    -SourceSha '7cdc281fb72566480f63b7c6f452c81bd86c99d2' `
    -ArtifactPath 'C:\path\to\active-cell-pp-api-server-0.3.23.zip' `
    -ServiceName 'CellMaxActiveCellPpApi' `
    -ExecutablePath 'active-cell-pp-api-server.exe' `
    -HealthUrl 'http://127.0.0.1:8765/health' `
    -HealthServiceId 'active-cell-pp-api' `
    -HealthExpectedVersion '0.3.23' `
    -Credential $stationCredential
```

Success means all three proofs agree: the staged artifact SHA-256, the station's atomic result for that deployment ID, and the independently queried remote health `service_id` plus version. The station keeps a restricted transaction journal and release marker so an interrupted deployment can resume with its original rollback target. A failed rollout records explicit old-service rollback health evidence when rollback succeeds; rollback failure is included in the error.

Protocol v1 trusts the restricted SMB deployment principal as the release authority for only the station-local allowlisted PP/AC services; detached manifest signatures and SSH/SFTP transport are intentionally later additions. It upgrades an existing NSSM service only and never performs a first service installation.

## Dev HTTP proxy (integrated, optional extra)

Core `**cmx-remote-access**` stays **FastAPI-only**. The dev reverse proxy (`cmx_remote_access.proxy`) needs a few more wheels — install with the `**proxy`** extra:

```bash
poetry install -E proxy
# optional: copy .env.proxy.example → .env and edit
export CMX_PROXY_UPSTREAM_URL=http://127.0.0.1:8765
poetry run cmx-remote-proxy
```

It forwards to `**CMX_PROXY_UPSTREAM_URL**` and stamps `**X-CMX-Remote-Proxy-Version**` (name: `REMOTE_ACCESS_PROXY_VERSION_HEADER` in `contracts`). Default bind: `**127.0.0.1:8780**`. Proxy-only health: `**GET /proxy/health**`.

If you run `**poetry install**` (no extra) from **active-cell-api** or **file-converter**, you will see a large tree — that comes from **those** projects’ dependencies, not from this library.

## Tests

```bash
poetry install && poetry run pytest -q
```
