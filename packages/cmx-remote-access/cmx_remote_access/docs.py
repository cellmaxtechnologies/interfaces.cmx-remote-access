from __future__ import annotations

import argparse
import re
import tomllib
from datetime import date
from pathlib import Path


def _project_metadata(project_dir: Path) -> dict[str, str]:
    data = tomllib.loads((project_dir / "pyproject.toml").read_text(encoding="utf-8"))
    poetry = data.get("tool", {}).get("poetry", {})
    name = str(poetry.get("name", project_dir.name))
    version = str(poetry.get("version", "0.0.0"))
    description = str(poetry.get("description", "") or "")
    return {"name": name, "version": version, "description": description}


def _latex_escape(text: str) -> str:
    replacements = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    return "".join(replacements.get(char, char) for char in text)


def _inline_markdown_to_latex(text: str) -> str:
    escaped = _latex_escape(text)
    escaped = re.sub(r"`([^`]+)`", r"\\texttt{\1}", escaped)
    escaped = re.sub(r"\*\*([^*]+)\*\*", r"\\textbf{\1}", escaped)
    return escaped


def _is_table_separator(line: str) -> bool:
    stripped = line.strip()
    return bool(stripped) and set(stripped.replace("|", "").replace(":", "").replace("-", "").strip()) == set()


def _table_to_latex(lines: list[str]) -> list[str]:
    rows = [[cell.strip() for cell in line.strip().strip("|").split("|")] for line in lines if not _is_table_separator(line)]
    if not rows:
        return []
    columns = max(len(row) for row in rows)
    spec = " ".join(["X"] * columns)
    out = [r"\begin{tabularx}{\textwidth}{" + spec + r"}", r"\hline"]
    for index, row in enumerate(rows):
        padded = row + [""] * (columns - len(row))
        out.append(" & ".join(_inline_markdown_to_latex(cell) for cell in padded) + r" \\")
        out.append(r"\hline" if index == 0 else r"")
    out.append(r"\end{tabularx}")
    return [line for line in out if line != ""]


def markdown_to_latex(markdown: str) -> str:
    """Convert the README Markdown subset used by package docs into LaTeX."""
    output: list[str] = []
    in_code = False
    in_list = False
    table_lines: list[str] = []

    def flush_table() -> None:
        nonlocal table_lines
        if table_lines:
            output.extend(_table_to_latex(table_lines))
            output.append("")
            table_lines = []

    def close_list() -> None:
        nonlocal in_list
        if in_list:
            output.append(r"\end{itemize}")
            output.append("")
            in_list = False

    for raw_line in markdown.splitlines():
        line = raw_line.rstrip()

        if line.startswith("```"):
            flush_table()
            close_list()
            if in_code:
                output.append(r"\end{Verbatim}")
                output.append("")
            else:
                output.append(r"\begin{Verbatim}[breaklines=true,fontsize=\small]")
            in_code = not in_code
            continue

        if in_code:
            output.append(line)
            continue

        if "|" in line and line.strip().startswith("|"):
            close_list()
            table_lines.append(line)
            continue
        flush_table()

        if not line.strip():
            close_list()
            output.append("")
            continue

        heading = re.match(r"^(#{1,4})\s+(.+)$", line)
        if heading:
            close_list()
            level = len(heading.group(1))
            title = _inline_markdown_to_latex(heading.group(2))
            command = {1: "chapter", 2: "section", 3: "subsection", 4: "subsubsection"}[level]
            output.append(f"\\{command}{{{title}}}")
            continue

        bullet = re.match(r"^\s*[-*]\s+(.+)$", line)
        if bullet:
            if not in_list:
                output.append(r"\begin{itemize}")
                in_list = True
            output.append(r"\item " + _inline_markdown_to_latex(bullet.group(1)))
            continue

        close_list()
        output.append(_inline_markdown_to_latex(line))

    flush_table()
    close_list()
    if in_code:
        output.append(r"\end{Verbatim}")
    return "\n".join(output).strip() + "\n"


def _extract_release_history(readme: str, version: str) -> list[tuple[str, str, str]]:
    marker = re.search(r"^## Release History\s*$", readme, flags=re.MULTILINE)
    if not marker:
        return [(version, date.today().isoformat(), "Initial generated documentation.")]
    section = readme[marker.end() :]
    next_section = re.search(r"^##\s+", section, flags=re.MULTILINE)
    if next_section:
        section = section[: next_section.start()]
    rows: list[tuple[str, str, str]] = []
    for line in section.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|") or _is_table_separator(stripped):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if len(cells) < 3 or cells[0].lower() == "version":
            continue
        rows.append((cells[0], cells[1], cells[2]))
    return rows or [(version, date.today().isoformat(), "Initial generated documentation.")]


def render_document(project_dir: Path, output_path: Path) -> None:
    """Render a package README and release history into a LaTeX document."""
    meta = _project_metadata(project_dir)
    readme_path = project_dir / "README.md"
    readme = readme_path.read_text(encoding="utf-8") if readme_path.exists() else f"# {meta['name']}\n"
    history = _extract_release_history(readme, meta["version"])
    body = markdown_to_latex(readme)

    rows = "\n".join(
        f"{_latex_escape(version)} & {_latex_escape(day)} & {_inline_markdown_to_latex(note)} \\\\"
        for version, day, note in history
    )

    title = _latex_escape(meta["name"])
    description = _latex_escape(meta["description"])
    tex = rf"""\documentclass[12pt,a4paper]{{report}}
\usepackage[utf8]{{inputenc}}
\usepackage[T1]{{fontenc}}
\usepackage[english]{{babel}}
\usepackage[hidelinks]{{hyperref}}
\usepackage[margin=20mm]{{geometry}}
\usepackage{{array}}
\usepackage{{tabularx}}
\usepackage{{fancyvrb}}
\usepackage{{longtable}}
\usepackage{{setspace}}
\onehalfspacing

\title{{{title} \\ \large API Documentation}}
\author{{CellMax Technologies}}
\date{{Version {meta["version"]} -- \today}}

\begin{{document}}
\sloppy
\maketitle

\begin{{abstract}}
{description}
\end{{abstract}}

\begin{{center}}
\textbf{{Revision History}}\\[1em]
\begin{{tabularx}}{{\textwidth}}{{l l X}}
\hline
\textbf{{Version}} & \textbf{{Date}} & \textbf{{Notes}} \\
\hline
{rows}
\hline
\end{{tabularx}}
\end{{center}}

\tableofcontents
\clearpage

{body}

\end{{document}}
"""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(tex, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate LaTeX documentation from a package README.")
    parser.add_argument("--project-dir", default=".", help="Package repository root.")
    parser.add_argument("--output", default="documentation/documentation.tex", help="Output .tex path.")
    args = parser.parse_args()

    project_dir = Path(args.project_dir).resolve()
    output = Path(args.output)
    if not output.is_absolute():
        output = project_dir / output
    render_document(project_dir, output)
    print(output)


if __name__ == "__main__":
    main()
