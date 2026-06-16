from cmx_remote_access.deployment import load_station_inventory


def test_station_inventory_contains_ret_stations() -> None:
    stations = {station.station_id: station for station in load_station_inventory()}

    assert stations["CMPROD-GOT-RETA"].computer_name == "CMPROD-GOT-RETA"
    assert stations["CMPROD-GOT-RETA"].endpoint.host == "10.0.245.179"
    assert stations["CMPROD-GOT-RETA"].endpoint.transport == "smb"

    assert stations["CMPROD-GOT-RETB"].computer_name == "CMPROD-GOT-RETB"
    assert stations["CMPROD-GOT-RETB"].endpoint.host == "10.0.245.144"
    assert stations["CMPROD-GOT-RETB"].endpoint.transport == "smb"


def test_station_computer_names_fit_windows_limit() -> None:
    for station in load_station_inventory():
        assert len(station.computer_name) <= 15


def test_station_ids_match_computer_names() -> None:
    for station in load_station_inventory():
        assert station.station_id == station.computer_name
