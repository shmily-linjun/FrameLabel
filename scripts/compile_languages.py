"""Compile the Qt translation files, and (for release builds) resources.py.

Daily translation work only needs ``.qm`` files: the application loads them
from ``anylabeling/resources/translations`` first, so ``resources.py`` does not
have to be regenerated for every string change.  Run the script without
``--no-resources`` before packaging so the embedded copy is up to date too.
"""

import argparse
import os
import shutil
import subprocess
import sys


def find_lrelease() -> str:
    """Return an available Qt Linguist release compiler."""
    candidates = ("lrelease", "lrelease-qt6", "pyside6-lrelease")
    for candidate in candidates:
        executable = shutil.which(candidate)
        if executable:
            return executable
    raise RuntimeError(
        "No Qt translation compiler found. Install lrelease or ensure "
        "pyside6-lrelease is available in the active environment."
    )


def compile_resources(output: str, qrc: str) -> None:
    """Compile a .qrc file to a PyQt6-compatible resources.py."""

    def normalize_imports(path: str) -> None:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        content = content.replace("from PySide6", "from PyQt6")
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)

    def add_rcc_commands(commands, base_command, needs_rewrite):
        # Force zlib resources when supported. Newer RCC builds may emit zstd
        # entries by default, which are not readable in some Windows Qt runtimes.
        commands.append(
            (
                [*base_command, "--compress-algo", "zlib", "-o", output, qrc],
                needs_rewrite,
            )
        )
        commands.append(([*base_command, "-o", output, qrc], needs_rewrite))

    commands = []
    add_rcc_commands(
        commands, [sys.executable, "-m", "PyQt6.pyrcc_main"], False
    )
    add_rcc_commands(commands, ["pyrcc6"], False)
    add_rcc_commands(commands, ["pyside6-rcc"], True)
    add_rcc_commands(commands, ["rcc", "-g", "python"], True)
    lrelease = shutil.which("lrelease")
    if lrelease:
        sibling_rcc = os.path.join(os.path.dirname(lrelease), "rcc")
        add_rcc_commands(commands, [sibling_rcc, "-g", "python"], True)
    for command, needs_rewrite in commands:
        executable = command[0]
        if executable != sys.executable and not shutil.which(executable):
            continue
        result = subprocess.run(command, stderr=subprocess.DEVNULL)
        if result.returncode != 0:
            continue
        if needs_rewrite:
            normalize_imports(output)
        return
    print(
        "Error: no Qt resource compiler found. Tried python -m "
        "PyQt6.pyrcc_main, pyrcc6, pyside6-rcc, rcc -g python, and "
        "lrelease-sibling rcc."
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--no-resources",
        action="store_true",
        help=(
            "compile only the .qm files; the app loads them from disk.  Use "
            "the default behaviour before packaging to refresh resources.py."
        ),
    )
    args = parser.parse_args()

    supported_languages = ["en_US", "zh_CN", "ja_JP", "ko_KR"]
    lrelease = find_lrelease()
    for language in supported_languages:
        subprocess.run(
            [
                lrelease,
                f"anylabeling/resources/translations/{language}.ts",
            ],
            check=True,
        )

    if args.no_resources:
        print(
            "Skipped resources.py; run without --no-resources before "
            "packaging to embed the new translations."
        )
        return

    compile_resources(
        output="anylabeling/resources/resources.py",
        qrc="anylabeling/resources/resources.qrc",
    )


if __name__ == "__main__":
    main()
