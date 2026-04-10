# cmx-server-interface

Umbrella for **network-facing services** and **shared contracts** used across **development** and **production** stacks. It is the interface layer behind **one company-wide view** of computers, **hardware**, **applications**, and **databases**.

## Two systems, same interfaces

| Repository | Path | Role |
|------------|------|------|
| **cmx-development-system** | `dev/apps/cmx-development-system` | Lab / R&D / engineering hosts; reuse production-style tests and flows on **lab equipment** and dev machines. |
| **cmx-production-system** | `prod/apps/cmx-production-system` | Manufacturing execution, stations, traceability. |

Both:

- Run largely via **Docker** (compose, overlays, agents).
- Communicate with **remote computers** and whatever runs there (**apps** and/or **hardware gateways**).
- Should consume the **same command/auth/health patterns** and **similar server shapes** defined here—not duplicate ad hoc APIs per environment.

## Three pillars (per computer)

| Pillar | When to use |
|--------|-------------|
| **Hardware** | Direct device access (serial, VISA, station I/O); use **proxies** in CI/dev. |
| **Applications** | **Interface the app** when installs are heavy, tools are third-party, or the app already owns the hardware (COM, local HTTP, CLI). |
| **Databases** | DB and related services (including Dockerized) that should appear next to hardware/apps for that host. |

## One dashboard (company-wide)

Monitoring is **not** “production-only.” The aim is **one tree-style dashboard** over **all relevant machines**: production floors, labs, and development—each node listing **applications**, **hardware**, and **databases** as appropriate.

The **dashboard application** lives in its own repo: **`cmx-dashboard`**, at **`cellmaxtechnologies/cmx-dashboard`** (root of this workspace—not under `interfaces/`). Interface packages stay under **`interfaces/cmx-server-interface`**.

## Layout

- `packages/` — services and libraries (e.g. PDM API, hardware gateway package, future shared auth/envelope libraries).

## Path

`cellmaxtechnologies/interfaces/cmx-server-interface`  
(Dotted: `cellmaxtechnologies.interfaces.cmx-server-interface`.)
