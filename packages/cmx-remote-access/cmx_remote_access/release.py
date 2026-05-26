from __future__ import annotations

import argparse
import re
import tomllib
from datetime import date
from pathlib import Path

from cmx_remote_access.docs import render_document


VERSION_RE = re.compile(r'(^version\s*=\s*")([^"]+)(")', flags=re.MULTILINE)
PY_VERSION_RE = re.compile(r'(__version__\s*=\s*")([^"]+)(")')
SERVICE_VERSION_RE = re.compile(r'(_SERVICE_VERSION\s*=\s*")([^"]+)(")')


def read_project_version(project_dir: Path) -> str:
    """Read ``tool.poetry.version`` from a package repository."""
    pyproject = project_dir / "pyproject.toml"
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    version = data.get("tool", {}).get("poetry", {}).get("version")
    if not version:
        raise ValueError(f"Could not read tool.poetry.version from {pyproject}")
    return str(version)


def bump_version(version: str, bump: str) -> str:
    """Return the next semantic version for ``major``, ``minor``, or ``patch``."""
    parts = version.split(".")
    if len(parts) != 3 or not all(part.isdigit() for part in parts):
        raise ValueError(f"Expected semantic version x.y.z, got {version!r}")
    major, minor, patch = (int(part) for part in parts)
    if bump == "major":
        return f"{major + 1}.0.0"
    if bump == "minor":
        return f"{major}.{minor + 1}.0"
    if bump == "patch":
        return f"{major}.{minor}.{patch + 1}"
    raise ValueError(f"Unknown bump kind: {bump}")


def update_pyproject(project_dir: Path, old_version: str, new_version: str) -> None:
    """Update the Poetry version in ``pyproject.toml``."""
    path = project_dir / "pyproject.toml"
    text = path.read_text(encoding="utf-8")
    updated, count = VERSION_RE.subn(rf"\g<1>{new_version}\3", text, count=1)
    if count != 1:
        raise ValueError(f"Could not update version in {path}")
    path.write_text(updated, encoding="utf-8")


def update_python_version_constants(project_dir: Path, old_version: str, new_version: str) -> list[Path]:
    """Update common Python version constants and defaults under a package repo."""
    changed: list[Path] = []
    for path in project_dir.rglob("*.py"):
        if any(part in {".venv", "build", "dist", "dist-bundle", "__pycache__"} for part in path.parts):
            continue
        text = path.read_text(encoding="utf-8")
        updated = PY_VERSION_RE.sub(rf"\g<1>{new_version}\3", text)
        updated = SERVICE_VERSION_RE.sub(rf"\g<1>{new_version}\3", updated)
        updated = updated.replace(f'default="{old_version}"', f'default="{new_version}"')
        updated = updated.replace(f"default='{old_version}'", f"default='{new_version}'")
        if updated != text:
            path.write_text(updated, encoding="utf-8")
            changed.append(path)
    return changed


def release_row(version: str, day: str, note: str) -> str:
    """Format one README release-history table row."""
    return f"| {version} | {day} | {note.strip()} |"


def ensure_release_history(readme: Path, version: str, note: str, day: str) -> None:
    """Ensure README contains a release-history row for the new version."""
    if not readme.exists():
        readme.write_text(f"# {readme.parent.name}\n\n", encoding="utf-8")

    text = readme.read_text(encoding="utf-8")
    row = release_row(version, day, note)
    marker = re.search(r"^## Release History\s*$", text, flags=re.MULTILINE)
    table_header = "## Release History\n\n| Version | Date | Notes |\n|---|---|---|\n"

    if not marker:
        heading = re.search(r"^# .+$", text, flags=re.MULTILINE)
        insert_at = heading.end() if heading else 0
        prefix = text[:insert_at].rstrip()
        suffix = text[insert_at:].lstrip("\n")
        new_section = f"{table_header}{row}\n\n"
        readme.write_text(f"{prefix}\n\n{new_section}{suffix}", encoding="utf-8")
        return

    section_start = marker.end()
    rest = text[section_start:]
    if row in rest.split("\n\n", 1)[0]:
        return

    first_table_row = re.search(r"^\|", rest, flags=re.MULTILINE)
    if not first_table_row:
        updated = text[: section_start] + "\n\n| Version | Date | Notes |\n|---|---|---|\n" + row + "\n" + rest
        readme.write_text(updated, encoding="utf-8")
        return

    separator = re.search(r"^\|[-:\s|]+\|\s*$", rest, flags=re.MULTILINE)
    if not separator:
        raise ValueError(f"Release History table in {readme} is missing a separator row")
    insert_at = section_start + separator.end()
    updated = text[:insert_at] + "\n" + row + text[insert_at:]
    readme.write_text(updated, encoding="utf-8")


def run_release(project_dir: Path, bump: str, note: str, day: str) -> str:
    """Bump version, update README release history, and regenerate LaTeX docs."""
    old_version = read_project_version(project_dir)
    new_version = bump_version(old_version, bump)
    update_pyproject(project_dir, old_version, new_version)
    update_python_version_constants(project_dir, old_version, new_version)
    ensure_release_history(project_dir / "README.md", new_version, note, day)
    render_document(project_dir, project_dir / "documentation" / "documentation.tex")
    return new_version


def main() -> None:
    parser = argparse.ArgumentParser(description="Bump a CRA package version and regenerate README-based LaTeX documentation.")
    parser.add_argument("--project-dir", default=".", help="Package repository root.")
    parser.add_argument("--bump", choices=["patch", "minor", "major"], required=True, help="Semantic version bump kind.")
    parser.add_argument("--note", required=True, help="Release-history note and recommended commit statement.")
    parser.add_argument("--date", default=date.today().isoformat(), help="Release date for the README table.")
    args = parser.parse_args()

    project_dir = Path(args.project_dir).resolve()
    version = run_release(project_dir, args.bump, args.note, args.date)
    print(f"{project_dir.name} -> {version}")
    print(f"Commit statement: {args.note}")


if __name__ == "__main__":
    main()
