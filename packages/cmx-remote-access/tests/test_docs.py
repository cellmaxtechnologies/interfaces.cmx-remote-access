from pathlib import Path

from cmx_remote_access.docs import _documentation_abstract


PACKAGE_ROOT = Path(__file__).resolve().parents[1]


def test_documentation_abstract_explains_how_to_read_document_without_description() -> None:
    abstract = _documentation_abstract({"name": "example-api", "version": "1.2.3", "description": ""})

    assert "example-api API package" in abstract
    assert "Release History first" in abstract
    assert "installation sections" in abstract


def test_documentation_abstract_ignores_placeholder_description() -> None:
    abstract = _documentation_abstract(
        {"name": "example-api", "version": "1.2.3", "description": "Add your description here"}
    )

    assert "Add your description here" not in abstract


def test_documentation_abstract_keeps_real_description() -> None:
    abstract = _documentation_abstract(
        {"name": "example-api", "version": "1.2.3", "description": "Controls a test instrument."}
    )

    assert "Controls a test instrument." in abstract


def test_desktop_bg8o674_pp_deployment_runbook_pins_machine_contract() -> None:
    runbook = (
        PACKAGE_ROOT / "docs" / "stations" / "DESKTOP-BG8O674-active-cell-pp-api.md"
    ).read_text(encoding="utf-8")

    for required in (
        "DESKTOP-BG8O674",
        r"\\DESKTOP-BG8O674\CellmaxDeploy$",
        "CELLMAX\\developer",
        "CellMax Deployment Agent",
        "CellMaxActiveCellPpApi",
        "DESKTOP-BG8O674\\ittab",
        "http://127.0.0.1:8765/health",
        r"C:\ProgramData\CellMax\active-cell-pp-api\.env",
        "ACTIVE_CELL_PP_API_UNC_TARGET",
        "never enter secrets",
        "same deployment ID",
        "SSH/SFTP",
    ):
        assert required in runbook
