# cmx-remote-access

Umbrella for **network-facing services** and **shared contracts** used across **development** and **production** stacks. The name avoids repeating “interface”: this repo already lives under **`interfaces/`**, and on GitHub it is **`interfaces.cmx-remote-access`**.

It is the **remote access** layer behind **one company-wide view** of computers, **hardware**, **applications**, and **databases**.

## Two systems, same contracts

| Repository | Path | Role |
|------------|------|------|
| **cmx-development-system** | `dev/apps/cmx-development-system` | Lab / R&D / engineering hosts; reuse production-style tests and flows on **lab equipment** and dev machines. |
| **cmx-production-system** | `prod/apps/cmx-production-system` | Manufacturing execution, stations, traceability. |

Both:

- Run largely via **Docker** (compose, overlays, agents).
- Communicate with **remote computers** and whatever runs there (**apps** and/or **hardware gateways**).
- Should consume the **same command/auth/health patterns** and **similar service shapes** defined here—not duplicate ad hoc APIs per environment.

## Three pillars (per computer)

| Pillar | When to use |
|--------|-------------|
| **Hardware** | Direct device access (serial, VISA, station I/O); use **proxies** in CI/dev. |
| **Applications** | **Bridge the app** when installs are heavy, tools are third-party, or the app already owns the hardware (COM, local HTTP, CLI). |
| **Databases** | DB and related services (including Dockerized) that should appear next to hardware/apps for that host. |

## Python vs HTTP

CRA-backed packages should keep the direct Python API and the HTTP transport separate:

- the package owns domain functions/classes with docstrings that explain the callable contract
- `cmx-remote-access` owns bearer auth, health payloads, client remote-mode resolution, installer/build helpers, and shared service conventions
- a package-level HTTP client mirrors the public Python operations when the caller is not on the machine that owns COM, hardware, or database access
- READMEs describe what the package is, why it exists, how it is deployed, and where it is used; generated LaTeX documentation is built from the README

This keeps docs from drifting into duplicated API reference while still making direct requests and Python function calls easy to relate.

## One dashboard (company-wide)

Monitoring is **not** “production-only.” The aim is **one tree-style dashboard** over **all relevant machines**: production floors, labs, and development—each node listing **applications**, **hardware**, and **databases** as appropriate.

The **dashboard application** is **`cmx-dashboard`** at **`cellmaxtechnologies/cmx-dashboard`**. Shared packages and contracts live here under **`interfaces/cmx-remote-access`**.

## Layout

- `packages/cmx-remote-access/` — **Python library** (`cmx_remote_access`): shared **RemoteCommand/RemoteResult** contracts, **FastAPI bearer auth** (`SERVICE_API_TOKEN`, `ADMIN_API_TOKEN`, `AUTH_STRICT`), plus an **optional dev HTTP reverse proxy** (`poetry run cmx-remote-proxy`; see `packages/cmx-remote-access/README.md`).
- `packages/cmx-remote-access/scripts/CmxInstallCore.ps1` — **shared Windows installer core**; each product ships an `install.ps1` that dot-sources it (see `packages/cmx-remote-access/docs/INSTALLATION.md`).
- `packages/cmx-remote-access/cmx_remote_access/deployment_inventory.json` — shared station inventory. It keeps long station ids such as `CM-PROD-GOT-RET-A` separate from short Windows computer names such as `CM-GOT-RET-A`.
- `packages/cmx-remote-access/scripts/Initialize-CmxStation.ps1` — local elevated PowerShell script for standardizing a Windows station account, shares, optional SSH readiness, station metadata, and computer name.
- `packages/pdm-api/` — PDM HTTP integration (existing).

## Paths

| | |
|--|--|
| **Workspace folder** | `cellmaxtechnologies/interfaces/cmx-remote-access` |
| **GitHub** | `cellmaxtechnologies/interfaces.cmx-remote-access` |
| **Dotted label** | `cellmaxtechnologies.interfaces.cmx-remote-access` |
