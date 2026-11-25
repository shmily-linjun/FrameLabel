"""Find translatable strings and keep the ``.ts`` files complete.

``pylupdate6`` only records ``*.tr(...)`` calls that are written inside a
class body.  The labeling window builds most of its dialogs, menus and
messages in module-level functions (``host.tr`` / ``self.tr``); those calls
work at runtime (Qt looks the string up with the receiver's class name) but
the extractor records nothing, so the text silently stays English.

This module implements the missing half:

* :func:`scan` walks ``anylabeling`` and reports every constant translatable
  string together with the context Qt will use at run time;
* :func:`missing_entries` lists the ``(context, source)`` pairs a ``.ts`` file
  does not contain yet (the guard test uses this);
* :func:`add_missing` appends them to a ``.ts`` file in the same format
  ``pylupdate6`` writes, reusing an existing translation for the same source
  when one exists.

Rules for the runtime context:

* ``QCoreApplication.translate("Context", "text")`` -> ``Context``;
* ``self.tr("text")`` inside a class -> that class;
* ``receiver.tr("text")`` anywhere else -> the module-level ``TR_CONTEXT``
  constant, which records the receiver's class; without it the call is
  reported as *unresolved* instead of guessing.

Calling ``other_widget.tr(...)`` inside a class method is also reported as
unresolved: the extractor would record the enclosing class while the runtime
looks up the other widget's class.
"""

from __future__ import annotations

import ast
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from xml.sax.saxutils import escape

TR_CONTEXT_NAME = "TR_CONTEXT"
CONTEXT_ATTR = "_fork_translation_context"


@dataclass(frozen=True)
class Entry:
    """One translatable string and the context it is registered under."""

    path: str
    line: int
    context: str
    text: str


@dataclass
class ScanResult:
    entries: list
    unresolved: list


def _iter_python_files(root):
    for base, directories, files in os.walk(root):
        directories[:] = sorted(
            name for name in directories if name != "__pycache__"
        )
        for name in sorted(files):
            if name.endswith(".py"):
                yield Path(base) / name


def _constant_arg(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _module_context(tree):
    for statement in tree.body:
        if not isinstance(statement, ast.Assign):
            continue
        for target in statement.targets:
            if (
                isinstance(target, ast.Name)
                and target.id == TR_CONTEXT_NAME
            ):
                value = _constant_arg(statement.value)
                if value:
                    return value
    return None


def _call_name(call):
    func = call.func
    if isinstance(func, ast.Attribute):
        return func.attr, func.value
    if isinstance(func, ast.Name):
        return func.id, None
    return None, None


def _receiver_label(receiver):
    if isinstance(receiver, ast.Name):
        return receiver.id
    if isinstance(receiver, ast.Attribute):
        return receiver.attr
    return "?"


def scan(root="anylabeling") -> ScanResult:
    """Return every constant translatable string under ``root``."""

    root_path = Path(root)
    entries = []
    unresolved = []
    for path in _iter_python_files(root_path):
        relative = path.as_posix()
        source_text = path.read_text(encoding="utf-8")
        tree = ast.parse(source_text, filename=str(path))
        module_context = _module_context(tree)

        def walk(body, class_name):
            for node in body:
                if isinstance(node, ast.ClassDef):
                    walk(node.body, node.name)
                    continue
                if isinstance(
                    node, (ast.FunctionDef, ast.AsyncFunctionDef)
                ):
                    walk(node.body, class_name)
                    continue
                if isinstance(node, ast.Call):
                    _collect_call(
                        node,
                        relative,
                        class_name,
                        module_context,
                        entries,
                        unresolved,
                    )
                for child in ast.iter_child_nodes(node):
                    if isinstance(
                        child,
                        (
                            ast.ClassDef,
                            ast.FunctionDef,
                            ast.AsyncFunctionDef,
                        ),
                    ):
                        continue
                    walk([child], class_name)

        walk(tree.body, None)
    entries.sort(key=lambda entry: (entry.path, entry.line, entry.text))
    return ScanResult(entries=entries, unresolved=unresolved)


def _collect_call(
    call, relative, class_name, module_context, entries, unresolved
):
    name, receiver = _call_name(call)
    if name is None:
        return
    line = getattr(call, "lineno", 0)

    if name == "translate":
        if len(call.args) < 2:
            return
        context = _constant_arg(call.args[0])
        text = _constant_arg(call.args[1])
        if text is None:
            return
        if context is None:
            unresolved.append((relative, line, "translate(context=?)"))
            return
        entries.append(Entry(relative, line, context, text))
        return

    if name != "tr" or not call.args:
        return
    text = _constant_arg(call.args[0])
    if text is None:
        return

    receiver_name = _receiver_label(receiver)
    if receiver_name == "self" and class_name is not None:
        entries.append(Entry(relative, line, class_name, text))
        return
    if module_context:
        entries.append(Entry(relative, line, module_context, text))
        return
    unresolved.append(
        (
            relative,
            line,
            f"{receiver_name}.tr outside a class (no {TR_CONTEXT_NAME})",
        )
    )


def read_ts(path):
    """Return ``{(context, source): translation}`` for a ``.ts`` file."""

    text = Path(path).read_text(encoding="utf-8")
    result = {}
    for block in re.finditer(
        r"<context>(.*?)</context>", text, flags=re.DOTALL
    ):
        body = block.group(1)
        name_match = re.search(r"<name>(.*?)</name>", body, flags=re.DOTALL)
        if name_match is None:
            continue
        context = _unescape(name_match.group(1).strip())
        for message in re.finditer(
            r"<message>(.*?)</message>", body, flags=re.DOTALL
        ):
            payload = message.group(1)
            source_match = re.search(
                r"<source>(.*?)</source>", payload, flags=re.DOTALL
            )
            if source_match is None:
                continue
            source = _unescape(source_match.group(1))
            translation_match = re.search(
                r"<translation[^>]*>(.*?)</translation>",
                payload,
                flags=re.DOTALL,
            )
            translation = (
                _unescape(translation_match.group(1))
                if translation_match
                else ""
            )
            result[(context, source)] = translation
    return result


def _unescape(text):
    return (
        text.replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&apos;", "'")
        .replace("&amp;", "&")
    )


def missing_entries(result: ScanResult, ts_path) -> list:
    """Return the entries a ``.ts`` file does not register yet."""

    existing = read_ts(ts_path)
    missing = []
    seen = set()
    for entry in result.entries:
        key = (entry.context, entry.text)
        if key in existing or key in seen:
            continue
        seen.add(key)
        missing.append(entry)
    return missing


@dataclass
class TranslationMemory:
    """Translations captured before a ``.ts`` file is regenerated.

    ``exact`` keeps the context-specific translation; ``by_source`` is the
    fallback used when code moved to another class.  The exact match wins so
    that a shared source text (``Test``/``Val``) keeps its per-context wording.
    """

    exact: dict = field(default_factory=dict)
    by_source: dict = field(default_factory=dict)

    def get(self, context, source):
        return self.exact.get((context, source)) or self.by_source.get(
            source, ""
        )


def translation_memory(ts_path) -> TranslationMemory:
    """Return the finished translations of a ``.ts`` file."""

    memory = TranslationMemory()
    for (context, source), translation in read_ts(ts_path).items():
        if not translation:
            continue
        memory.exact.setdefault((context, source), translation)
        memory.by_source.setdefault(source, translation)
    return memory


_MESSAGE_BLOCK = re.compile(
    r"<message>(?:(?!</message>).)*?</message>", flags=re.DOTALL
)
_TRANSLATION = re.compile(
    r"<translation([^>]*)>(.*?)</translation>", flags=re.DOTALL
)


def _context_of(text, position):
    """Return the `<name>` of the context containing `position`."""

    start = text.rfind("<context>", 0, position)
    if start == -1:
        return ""
    end = text.find("</context>", position)
    block = text[start:end if end != -1 else len(text)]
    name = re.search(r"<name>(.*?)</name>", block, flags=re.DOTALL)
    return _unescape(name.group(1).strip()) if name else ""


def fill_translations(ts_path, memory) -> int:
    """Fill empty/unfinished translations from ``memory``; return the count."""

    text = Path(ts_path).read_text(encoding="utf-8")
    filled = 0

    def replace_block(match):
        nonlocal filled
        block = match.group(0)
        source_match = re.search(
            r"<source>(.*?)</source>", block, flags=re.DOTALL
        )
        if source_match is None:
            return block
        source = _unescape(source_match.group(1))
        context = _context_of(text, match.start())
        translation = memory.get(context, source)
        if not translation:
            return block
        translation_match = _TRANSLATION.search(block)
        if translation_match is None:
            return block
        attributes = translation_match.group(1)
        body = translation_match.group(2)
        if body.strip() and 'type="unfinished"' not in attributes:
            return block
        filled += 1
        replacement = (
            f"<translation>{escape(translation)}</translation>"
        )
        return (
            block[: translation_match.start()]
            + replacement
            + block[translation_match.end() :]
        )

    text = _MESSAGE_BLOCK.sub(replace_block, text)
    if filled:
        Path(ts_path).write_text(text, encoding="utf-8", newline="\n")
    return filled


def _location(entry, translations_dir):
    relative = os.path.relpath(
        os.path.abspath(entry.path), os.path.abspath(translations_dir)
    )
    return relative.replace("/", "\\")


def _message_block(entry, translations_dir, translation, unfinished):
    location = _location(entry, translations_dir)
    if unfinished:
        body = (
            '        <translation type="unfinished"></translation>'
        )
    else:
        body = f"        <translation>{escape(translation)}</translation>"
    return (
        "    <message>\n"
        f'        <location filename="{location}" line="{entry.line}" />\n'
        f"        <source>{escape(entry.text)}</source>\n"
        f"{body}\n"
        "    </message>\n"
    )


def add_missing(ts_path, entries, translations=None, memory=None):
    """Append ``entries`` to ``ts_path``; return the number added.

    ``translations`` maps a source string to a finished translation (used for
    the primary language); entries without one stay ``unfinished`` and fall
    back to the source text at run time.
    """

    text = Path(ts_path).read_text(encoding="utf-8")
    existing = read_ts(ts_path)
    translations = translations or {}
    memory = memory or TranslationMemory()

    by_context = {}
    seen = set()
    for entry in entries:
        key = (entry.context, entry.text)
        if key in existing or key in seen:
            continue
        seen.add(key)
        by_context.setdefault(entry.context, []).append(entry)

    translations_dir = str(Path(ts_path).parent)
    added = 0
    new_blocks = []
    for context in sorted(by_context):
        blocks = []
        for entry in sorted(
            by_context[context], key=lambda item: (item.path, item.line)
        ):
            translation = (
                memory.get(entry.context, entry.text)
                or translations.get(entry.text, "")
            )
            unfinished = not translation
            blocks.append(
                _message_block(
                    entry, translations_dir, translation, unfinished
                )
            )
            added += 1
        block = "".join(blocks)
        marker = f"    <name>{escape(context)}</name>"
        position = text.find(marker)
        if position == -1:
            new_blocks.append(
                f"  <context>\n{marker}\n{block}</context>\n"
            )
            continue
        close = text.find("</context>", position)
        if close == -1:
            new_blocks.append(f"  <context>\n{marker}\n{block}</context>\n")
            continue
        text = text[:close] + block + text[close:]

    if new_blocks:
        end = text.rfind("</TS>")
        text = text[:end] + "".join(new_blocks) + text[end:]
    Path(ts_path).write_text(text, encoding="utf-8", newline="\n")
    return added
