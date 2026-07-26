# CMX Remote Access

Status: development

## Why

This repo is the shared remote-access contract and service foundation for CellMax development and live systems.

It defines common authentication, health, command/result, installer, deployment, and station-inventory patterns for hardware, application, and database-facing services.

## Who

Owner: Developer. Contact: developer@cellmax.com.

## Dependencies

Runtime and package dependencies:

- Python `>=3.10, <3.14` for `packages/cmx-remote-access`.
- Poetry.
- FastAPI for shared HTTP service helpers.
- Optional `httpx`, `uvicorn`, and `python-dotenv` for the development proxy extra.
- PowerShell for shared Windows install, build, service, deployment, and station-initialization scripts.
- Windows service tooling through the vendored `tools/nssm.exe` helper.

Operational dependencies:

- CellMax workstation and station naming conventions.
- Service tokens such as `SERVICE_API_TOKEN` and `ADMIN_API_TOKEN`.
- Deployment inventory in `packages/cmx-remote-access/cmx_remote_access/deployment_inventory.json`.
- Consumer packages such as Active Cell APIs and PDM API that dot-source or import the shared CRA helpers.

## How

Install the core package from `packages/cmx-remote-access`:

```powershell
cd packages\cmx-remote-access
poetry install
```

Run tests:

```powershell
poetry run pytest
```

Run the optional development HTTP proxy when needed:

```powershell
poetry install --extras proxy
poetry run cmx-remote-proxy
```

Use the shared PowerShell scripts from `packages/cmx-remote-access/scripts` when building or installing CRA-backed services.

Product repositories should keep product-specific install entrypoints thin and delegate shared behavior to these scripts.

## What

Cmx Remote Access is the umbrella for CellMax network-facing service contracts and shared remote-access tooling.

It defines common service patterns for hardware, applications, and databases across development, lab, and live systems.

The `cmx_remote_access` Python package provides remote command/result contracts, authentication helpers, health payloads, client remote-mode resolution, release helpers, and a development proxy.

The repo also contains shared Windows installer, build, and service scripts plus deployment inventory used by service packages.

The intended architecture is one company-wide machine tree where hardware bridges, application bridges, and database services expose compatible health and command surfaces rather than each environment inventing its own API.

The repo also includes `packages/pdm-api`, an existing PDM integration package that uses the remote-access direction and should continue to align with the shared patterns here.
