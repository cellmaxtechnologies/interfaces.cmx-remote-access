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

## One dashboard (company-wide)

Monitoring is **not** “production-only.” The aim is **one tree-style dashboard** over **all relevant machines**: production floors, labs, and development—each node listing **applications**, **hardware**, and **databases** as appropriate.

The **dashboard application** is **`cmx-dashboard`** at **`cellmaxtechnologies/cmx-dashboard`**. Shared packages and contracts live here under **`interfaces/cmx-remote-access`**.

## Layout

- `packages/cmx-remote-access/` — **Python library** (`cmx_remote_access`): shared **RemoteCommand/RemoteResult** contracts, **FastAPI bearer auth** (`SERVICE_API_TOKEN`, `ADMIN_API_TOKEN`, `AUTH_STRICT`), plus an **optional dev HTTP reverse proxy** (`poetry run cmx-remote-proxy`; see `packages/cmx-remote-access/README.md`).
- `packages/cmx-remote-access/scripts/CmxInstallCore.ps1` — **shared Windows installer core**; each product ships an `install.ps1` that dot-sources it (see `packages/cmx-remote-access/docs/INSTALLATION.md`).
- `packages/pdm-api/` — PDM HTTP integration (existing).

## Paths

| | |
|--|--|
| **Workspace folder** | `cellmaxtechnologies/interfaces/cmx-remote-access` |
| **GitHub** | `cellmaxtechnologies/interfaces.cmx-remote-access` |
| **Dotted label** | `cellmaxtechnologies.interfaces.cmx-remote-access` |
