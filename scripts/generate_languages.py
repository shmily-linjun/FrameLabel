import argparse
import glob
import os
import shutil
import subprocess
import sys

from PyQt6 import QtCore

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from translation_scan import (  # noqa: E402
    add_missing,
    fill_translations,
    fill_identity,
    missing_entries,
    scan,
    translation_memory,
)


def find_tool(name: str) -> str:
    """Locate a Qt command line tool on PATH or in the active env."""

    executable = shutil.which(name)
    if executable:
        return executable
    for suffix in ("", ".exe"):
        candidate = os.path.join(sys.prefix, "Scripts", name + suffix)
        if os.path.isfile(candidate):
            return candidate
    raise RuntimeError(f"Required Qt tool not found: {name}")


def find_lrelease() -> str:
    """Return an available Qt Linguist release compiler."""

    for candidate in ("lrelease", "lrelease-qt6", "pyside6-lrelease"):
        try:
            return find_tool(candidate)
        except RuntimeError:
            continue
    raise RuntimeError(
        "No Qt translation compiler found. Install lrelease or ensure "
        "pyside6-lrelease is available in the active environment."
    )


def compile_resources(output: str, qrc: str) -> None:
    """Compile a .qrc file to a PyQt6-compatible resources.py."""

    def normalize_imports(path: str) -> None:
        """Rewrite PySide6 imports emitted by pyside6-rcc to PyQt6."""
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


def source_files(root: str = "anylabeling"):
    """Return the Python files that can contain translatable strings.

    Passing every ``*.py`` file exceeded the Windows command line limit, so
    only files that mention a translation call are listed.  Qt's own generated
    ``*_ui.py`` files are included because they call ``tr()`` too.
    """

    selected = []
    for path in sorted(glob.glob(os.path.join(root, "**", "*.py"), recursive=True)):
        if "__pycache__" in path:
            continue
        try:
            with open(path, "r", encoding="utf-8") as handle:
                content = handle.read()
        except OSError:
            continue
        if "tr(" in content or "translate(" in content:
            selected.append(path)
    return selected


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument(
    "--no-resources",
    action="store_true",
    help=(
        "compile only the .qm files; the app loads them from disk.  Use"
        " the default behaviour before packaging to refresh resources.py."
    ),
)
args = parser.parse_args()

supported_languages = ["en_US", "zh_CN", "ja_JP", "ko_KR"]
translations_path = "anylabeling/resources/translations"
lrelease = find_lrelease()
pylupdate = find_tool("pylupdate6")
pyuic = find_tool("pyuic6")

# Compile .ui files so pylupdate6 sees their generated *_ui.py sources.
for ui_file in glob.glob(os.path.join("**", "*.ui"), recursive=True):
    py_file = os.path.splitext(ui_file)[0] + "_ui.py"
    subprocess.run([pyuic, "-x", ui_file, "-o", py_file])

py_files = source_files()
print(f"Scanning {len(py_files)} source files for translatable strings")

# pylupdate6 cannot attribute ``*.tr()`` calls that live outside a class
# body; see scripts/translation_scan.py for the rules and the guard test in
# tests/test_i18n.  The supplemental pass below adds those strings with the
# context Qt uses at run time.
scan_result = scan()
print(
    f"Supplemental scan: {len(scan_result.entries)} strings, "
    f"{len(scan_result.unresolved)} unresolved"
)
if scan_result.unresolved:
    for path, line, label in scan_result.unresolved[:20]:
        print(f"  {path}:{line}: {label}")
    raise SystemExit(
        "Unresolved translation context; declare TR_CONTEXT or use "
        'QCoreApplication.translate("Context", ...).'
    )

for language in supported_languages:
    translation_file = f"{translations_path}/{language}.ts"
    # Keep the previous translations: pylupdate6 only reuses them for the
    # same context, and code that moved to another class would lose them.
    memory = translation_memory(translation_file)
    command = [pylupdate, "--no-obsolete", *py_files, "-ts", translation_file]
    result = subprocess.run(command)
    if result.returncode != 0:
        raise SystemExit(f"pylupdate6 failed for {language}")

    ts_path = translation_file
    pending = missing_entries(scan_result, ts_path)
    english = (
        {entry.text: entry.text for entry in scan_result.entries}
        if language == "en_US"
        else {}
    )
    added = add_missing(ts_path, pending, english, memory)
    restored = fill_translations(ts_path, memory)
    if language == "en_US":
        restored += fill_identity(ts_path)
    print(
        f"{language}: {len(pending)} supplemental strings, {added} added, "
        f"{restored} translations restored from the previous file"
    )

    subprocess.run([lrelease, ts_path], check=True)

if args.no_resources:
    print(
        "Skipped resources.py; run without --no-resources before"
        " packaging to embed the new translations."
    )
else:
    compile_resources(
        output="anylabeling/resources/resources.py",
        qrc="anylabeling/resources/resources.qrc",
    )
