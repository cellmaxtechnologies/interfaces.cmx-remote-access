"""Deployment station inventory contracts.

The inventory separates the stable production station id from the shorter
Windows computer name used for SMB/SSH access.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any, Literal

StationRole = Literal["final", "pre", "ret", "pack", "sbt", "meas", "test"]
DeploymentTransport = Literal["smb", "ssh"]


@dataclass(frozen=True, slots=True)
class DeploymentEndpoint:
    """How deployment tools currently reach a station."""

    transport: DeploymentTransport
    host: str | None = None
    applications_share: str | None = None
    applications_subdir: str | None = None
    desktop_share: str | None = None
    desktop_subdir: str | None = None


@dataclass(frozen=True, slots=True)
class DeploymentStation:
    """Stable station identity plus current remote-access details."""

    station_id: str
    computer_name: str
    role: StationRole
    site: str
    line: str
    endpoint: DeploymentEndpoint
    hardware: dict[str, Any]


@dataclass(frozen=True, slots=True)
class DeploymentSettingsIdentity:
    """Host-specific identity values that deployed applications write to settings."""

    station_id: str
    computer_name: str


def load_station_inventory(path: str | Path | None = None) -> list[DeploymentStation]:
    """Load the shared station deployment inventory."""

    if path is None:
        raw = resources.files(__package__).joinpath("deployment_inventory.json").read_text(encoding="utf-8")
    else:
        raw = Path(path).read_text(encoding="utf-8")

    payload = json.loads(raw)
    stations: list[DeploymentStation] = []
    for item in payload["stations"]:
        endpoint = DeploymentEndpoint(**item["endpoint"])
        stations.append(
            DeploymentStation(
                station_id=item["station_id"],
                computer_name=item["computer_name"],
                role=item["role"],
                site=item["site"],
                line=item["line"],
                endpoint=endpoint,
                hardware=item.get("hardware", {}),
            )
        )
    return stations


def find_station(identifier: str, path: str | Path | None = None) -> DeploymentStation:
    """Find a station by station id, computer name, or endpoint host."""

    normalized = identifier.upper().strip()
    for station in load_station_inventory(path):
        candidates = {
            station.station_id.upper(),
            station.computer_name.upper(),
        }
        if station.endpoint.host:
            candidates.add(station.endpoint.host.upper())
        if normalized in candidates:
            return station
    raise KeyError(f"No deployment station found for {identifier!r}")


def deployment_settings_identity(identifier: str, path: str | Path | None = None) -> DeploymentSettingsIdentity:
    """Return the identity values applications should write into host settings."""

    station = find_station(identifier, path)
    return DeploymentSettingsIdentity(
        station_id=station.station_id,
        computer_name=station.computer_name,
    )
