# cmx-remote-access (Python package)

## Release History

| Version | Date | Notes |
|---|---|---|
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
