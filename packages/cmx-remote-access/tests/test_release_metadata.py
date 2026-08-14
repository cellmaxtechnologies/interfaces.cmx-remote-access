from pathlib import Path
import tomllib


PACKAGE_ROOT = Path(__file__).resolve().parents[1]


def test_release_metadata_and_framework_lock_are_synchronized() -> None:
    with (PACKAGE_ROOT / "pyproject.toml").open("rb") as stream:
        project = tomllib.load(stream)
    with (PACKAGE_ROOT / "poetry.lock").open("rb") as stream:
        lock = tomllib.load(stream)

    poetry = project["tool"]["poetry"]
    assert poetry["version"] == "1.1.4"
    assert poetry["dependencies"]["fastapi"] == ">=0.115,<0.141"
    assert "| 1.1.4 |" in (PACKAGE_ROOT / "README.md").read_text(encoding="utf-8")

    locked_versions = {package["name"]: package["version"] for package in lock["package"]}
    assert locked_versions["fastapi"] == "0.140.0"
    assert locked_versions["starlette"] == "1.3.1"
