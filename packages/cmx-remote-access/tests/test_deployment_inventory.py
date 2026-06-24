from cmx_remote_access.deployment import deployment_settings_identity, find_station, load_station_inventory


def test_station_inventory_contains_ret_stations() -> None:
    stations = {station.station_id: station for station in load_station_inventory()}

    assert stations["CM-GOT-RET-A"].computer_name == "CM-GOT-RET-A"
    assert stations["CM-GOT-RET-A"].endpoint.host == "10.0.245.144"
    assert stations["CM-GOT-RET-A"].endpoint.transport == "smb"

    assert stations["CM-GOT-RET-B"].computer_name == "CM-GOT-RET-B"
    assert stations["CM-GOT-RET-B"].endpoint.host == "10.0.245.179"
    assert stations["CM-GOT-RET-B"].endpoint.transport == "smb"


def test_station_inventory_contains_sbt_station() -> None:
    stations = {station.station_id: station for station in load_station_inventory()}

    station = stations["CM-GOT-SBT-A"]
    assert station.computer_name == "CM-GOT-SBT-A"
    assert station.endpoint.host == "10.0.245.173"
    assert station.endpoint.transport == "smb"
    assert station.endpoint.applications_share == "CellmaxApplications"
    assert station.endpoint.desktop_share == "CellmaxDesktop"
    assert station.hardware["apps"] == [
        "sbt-ret-leakage-test",
        "sbt-ret-connection-test",
        "sbt-ret-qr-printer",
    ]


def test_station_inventory_contains_pim_only_pretest_b() -> None:
    stations = {station.station_id: station for station in load_station_inventory()}

    station = stations["CM-GOT-PRE-B"]
    assert station.endpoint.host == "10.0.245.171"
    assert station.endpoint.transport == "smb"
    assert station.endpoint.applications_share == "CellmaxApplications"
    assert station.endpoint.desktop_share == "CellmaxDesktop"
    assert station.endpoint.applications_subdir is None
    assert station.endpoint.desktop_subdir is None
    assert station.hardware == {
        "pim": True,
        "vna": False,
        "shaker": False,
    }


def test_station_inventory_contains_usa_placeholders() -> None:
    stations = {station.station_id: station for station in load_station_inventory()}

    assert stations["CM-USA-FIN-A"].endpoint.host is None
    assert stations["CM-USA-RET-A"].endpoint.host is None
    assert stations["CM-USA-PACK-A"].endpoint.host is None
    assert stations["CM-USA-RET-A"].role == "ret"
    assert stations["CM-USA-PACK-A"].role == "pack"


def test_station_inventory_uses_kis_station_names() -> None:
    stations = {station.station_id: station for station in load_station_inventory()}

    assert "CMDEV-KIS-MEASA" not in stations
    assert "CMDEV-KIS-MEASB" not in stations
    assert stations["CM-KIS-MEAS-A"].role == "meas"
    assert stations["CM-KIS-MEAS-B"].role == "meas"

    test_station = stations["CM-KIS-TEST-A"]
    assert test_station.role == "test"
    assert test_station.endpoint.transport == "ssh"
    assert test_station.endpoint.host is None
    assert test_station.hardware["apps"] == [
        "ret-calibrate-config",
        "pim-port-params-test",
    ]


def test_station_computer_names_fit_windows_limit() -> None:
    for station in load_station_inventory():
        assert len(station.computer_name) <= 15


def test_station_ids_match_computer_names() -> None:
    for station in load_station_inventory():
        assert station.station_id == station.computer_name


def test_ret_b_host_resolves_to_ret_b_settings_identity() -> None:
    identity = deployment_settings_identity("10.0.245.179")

    assert identity.station_id == "CM-GOT-RET-B"
    assert identity.computer_name == "CM-GOT-RET-B"


def test_find_station_accepts_host_and_names() -> None:
    assert find_station("10.0.245.144").station_id == "CM-GOT-RET-A"
    assert find_station("CM-GOT-RET-B").endpoint.host == "10.0.245.179"
    assert find_station("10.0.245.173").station_id == "CM-GOT-SBT-A"
    assert find_station("10.0.245.171").station_id == "CM-GOT-PRE-B"
