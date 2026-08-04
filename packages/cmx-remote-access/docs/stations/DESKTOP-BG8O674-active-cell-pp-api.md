# DESKTOP-BG8O674 active-cell-pp-api deployment

This is the durable, secret-free deployment contract for the PP API host `DESKTOP-BG8O674`. Commands run from the CellMax repository computer under `CELLMAX\developer` unless a step explicitly says it runs in an elevated PowerShell console on the station.

## Pinned station topology

| Item | Value |
|---|---|
| Station | `DESKTOP-BG8O674` |
| SMB publisher principal | `CELLMAX\developer` |
| Deployment share | `\\DESKTOP-BG8O674\CellmaxDeploy$` |
| Station transfer root | `C:\Cellmax\Deploy` |
| Agent task | `CellMax Deployment Agent`, LocalSystem, startup trigger |
| Agent protected root | `C:\ProgramData\CellMax\deployment-agent` |
| Package | `active-cell-pp-api` |
| Windows service | `CellMaxActiveCellPpApi` |
| Preserved service identity | `DESKTOP-BG8O674\ittab` (NSSM may report `.\ittab`) |
| Release executable | `active-cell-pp-api-server.exe` at archive root |
| Station health gate | `http://127.0.0.1:8765/health` |
| Publisher health gate | `http://DESKTOP-BG8O674:8765/health` |
| Expected service ID | `active-cell-pp-api` |
| Station-only configuration | `C:\ProgramData\CellMax\active-cell-pp-api\.env` |

The agent may change only NSSM `Application` and `AppDirectory`. It preserves the service identity, startup settings, tokens, COM/vendor configuration, and the ProgramData `.env` file.

## One-time bootstrap and agent upgrades

Build `cmx-deployment-agent-<version>.zip` with `scripts/New-CmxDeploymentAgentBundle.ps1`. Copy it to the station inbox, then run the included installer from an elevated station PowerShell console:

```powershell
.\Install-CmxDeploymentAgent.ps1 -DeploymentPrincipal 'CELLMAX\developer'
```

The bootstrap creates the hidden share and protected LocalSystem task. CRA 1.1.2 and later stop a running older task before registration and restart it with the newly installed scripts. Agent self-update is not part of deployment protocol v1, so this bootstrap upgrade remains an explicit elevated station action.

## Publish a PP release from the repository computer

Build the PP server ZIP in the sibling `packages/active-cell-pp-api` repository. A release has a new PP SemVer, exact source Git SHA, and SHA-256. Then run from this package's `scripts` directory:

```powershell
.\Publish-CmxServiceRelease.ps1 `
    -ComputerName 'DESKTOP-BG8O674' `
    -ShareName 'CellmaxDeploy$' `
    -PackageName 'active-cell-pp-api' `
    -PackageVersion $version `
    -SourceSha $sourceSha `
    -ArtifactPath $artifactPath `
    -ServiceName 'CellMaxActiveCellPpApi' `
    -ExecutablePath 'active-cell-pp-api-server.exe' `
    -HealthUrl 'http://127.0.0.1:8765/health' `
    -HealthServiceId 'active-cell-pp-api' `
    -HealthExpectedVersion $version
```

The current Windows session already uses the allowlisted `CELLMAX\developer` share principal, so a separate SMB credential is normally unnecessary. If Windows has no valid session, use `Get-Credential` and the publisher's `-Credential` parameter; never enter secrets in command-line arguments, source files, Git, manifests, bundles, SMB folders, logs, or chat.

The publisher writes the artifact and strict manifest first and the `ready` marker last. The LocalSystem runner claims the deployment into its protected queue, verifies the artifact hash and station allowlist, prepares an immutable versioned release, grants the unchanged service identity read/execute access, switches NSSM, and reports an atomic result only after exact health succeeds.

## PP data-share credentials

Interactive mappings owned by an IT desktop session do not enter the NSSM service logon session. Reference-mode jobs therefore require the NAS credential in the station-only `.env`:

```dotenv
ACTIVE_CELL_PP_API_UNC_TARGET=\\10.1.32.25\shares2
ACTIVE_CELL_PP_API_UNC_USERNAME=<fully-qualified NAS or domain account>
ACTIVE_CELL_PP_API_UNC_PASSWORD=<station-local secret>
```

The credential must open both `\\10.1.32.25\shares2` and `\\10.1.32.25\shares`. Configure it through a secure prompt on the station, never enter secrets into this runbook or the deployment transport, and restart `CellMaxActiveCellPpApi` after changing `.env`.

Before a real job, call authenticated `POST /v1/diagnostics/path-access` from the repository computer for every source, probe, CalCoeff, and output directory. Continue only when the response identifies version `0.3.23` or the intended later version, process user `DESKTOP-BG8O674\ittab`, a connected network-share target, and accessible paths.

## Success proof

A deployment is complete only when all of these agree:

1. Local artifact SHA-256 equals the manifest and station result SHA-256.
2. The result has `status: succeeded`, the intended versioned release path, `service_id: active-cell-pp-api`, and the intended version.
3. Independent `http://DESKTOP-BG8O674:8765/health` reports `status: ok`, exact service ID, and exact version.
4. For a processing release, an authenticated unique test job completes and produces a non-empty vendor-valid MD4 artifact without overwriting reference inputs.

The first proven agent deployment on this station installed PP `0.3.23` from source `7cdc281fb72566480f63b7c6f452c81bd86c99d2`, artifact SHA-256 `C335132FB16A0D9B7A4E5FC119310E5E6E212B53F1E5FC24483EF33CC6F1181A`, deployment ID `6ba776c8-be16-4cfd-937c-791cc5ea75a4`, and release root `C:\ProgramData\CellMax\deployment-agent\releases\active-cell-pp-api\0.3.23`.

## Failure and retry

The agent leaves the old service configuration untouched when failure occurs before the NSSM switch. After a switch failure, it restores and health-checks the recorded previous release.

If a deployment already prepared an immutable version directory, retry it only with the same deployment ID and unchanged artifact after correcting the station condition. Re-queue its `failed` marker as `ready`; do not publish the same package version under a new ID. A different artifact or source requires a new package version.

## Future SSH transport

SSH/SFTP replaces only SMB staging and activation. It must transfer the same ZIP and strict manifest, publish the same ready-last signal, and read the same atomic result while the same station agent owns allowlisting, privilege, locking, health checks, and rollback. Do not create a second SSH-specific installer or move station secrets into the SSH publisher.
