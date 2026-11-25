"""Find translatable strings and keep the ``.ts`` files complete.

``pylupdate6`` only records ``*.tr(...)`` calls that are written inside a
class body with a *literal* argument.  The labeling window also translates:

* text in module-level functions (``host.tr(...)``);
* ``self._tr("...")`` helpers that pin a module-level
  ``TRANSLATION_CONTEXT``;
* ``self.tr(CONSTANT)`` and ``for label in CONSTANTS: self.tr(label)`` where
  the constant lives in another module (statistics headers);
* ``QT_TRANSLATE_NOOP(context, "...")`` entries in the settings schema;
* the ``_translate("form", "...")`` calls generated from a ``.ui`` file.

Those strings work at run time but never reach the ``.ts`` files, so a
regeneration silently drops their translations (fork.49 regression: the right
sidebar lost its Chinese text).  This module implements the missing half:

* :func:`scan` walks ``anylabeling`` and reports every resolvable string
  together with the context Qt will use at run time;
* :func:`missing_entries` lists the ``(context, source)`` pairs a ``.ts`` file
  does not contain yet (the guard test uses this);
* :func:`add_missing` appends them to a ``.ts`` file in the same format
  ``pylupdate6`` writes, reusing an existing translation for the same source
  when one exists;
* :func:`translation_memory` / :func:`fill_translations` keep the curated
  translations when code moves to another class.

Context rules:

* ``QCoreApplication.translate("Context", "text")`` / ``_translate(...)`` ->
  the literal context;
* ``QT_TRANSLATE_NOOP(CONSTANT, "text")`` -> the constant's value;
* ``self.tr("text")`` inside a class -> that class;
* ``X._tr("text")`` -> the module's ``TRANSLATION_CONTEXT`` (that is what the
  helper passes to Qt); a delegated call such as
  ``host.label_manager_widget._tr(...)`` is skipped because the owner module
  registers the same string;
* ``receiver.tr("text")`` anywhere else -> the module-level ``TR_CONTEXT``
  constant (records the receiver's class); without it the call is reported as
  *unresolved* instead of guessing.

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
HELPER_CONTEXT_NAME = "TRANSLATION_CONTEXT"
HELPER_CONTEXT_SUFFIX = "_TRANSLATION_CONTEXT"
CONTEXT_ATTR = "_fork_translation_context"
TRANSLATE_NAMES = ("translate", "_translate")
NOOP_NAMES = ("QT_TRANSLATE_NOOP",)
TR_NAMES = ("tr", "_tr")


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


def _module_string_constants(tree):
    """Return module-level ``NAME -> str`` assignments."""

    values = {}
    for statement in tree.body:
        if not isinstance(statement, ast.Assign):
            continue
        value = _constant_arg(statement.value)
        if value is None:
            continue
        for target in statement.targets:
            if isinstance(target, ast.Name):
                values[target.id] = value
    return values


def _module_sequence_constants(tree, strings=None):
    """Return module-level ``NAME -> (str, ...)`` assignments.

    Elements may reference another module-level string constant
    (``COLUMN_HEADERS = (COLUMN_CLASS_LABEL, SPLIT_TRAIN, ...)``), so the
    module's own string constants are resolved first.
    """

    strings = strings or _module_string_constants(tree)
    values = {}
    for statement in tree.body:
        if not isinstance(statement, ast.Assign):
            continue
        if not isinstance(statement.value, (ast.Tuple, ast.List)):
            continue
        items = []
        for element in statement.value.elts:
            value = _constant_arg(element)
            if value is None and isinstance(element, ast.Name):
                value = strings.get(element.id)
            items.append(value)
        if not items or any(item is None for item in items):
            continue
        for target in statement.targets:
            if isinstance(target, ast.Name):
                values[target.id] = tuple(items)
    return values


def _module_contexts(tree):
    """Return ``(tr_context, helper_context)`` for one module."""

    strings = _module_string_constants(tree)
    tr_context = strings.get(TR_CONTEXT_NAME)
    helper_context = strings.get(HELPER_CONTEXT_NAME)
    if helper_context is None:
        for name, value in strings.items():
            if name.endswith(HELPER_CONTEXT_SUFFIX):
                helper_context = value
                break
    return tr_context, helper_context


def _build_project_tables(paths):
    """Collect module-level constants shared across files.

    Only names that every module agrees on are kept; an ambiguous name is
    dropped instead of guessing a wrong translation context.
    """

    strings = {}
    sequences = {}
    for path in paths:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError):
            continue
        for name, value in _module_string_constants(tree).items():
            strings.setdefault(name, set()).add(value)
        for name, values in _module_sequence_constants(tree).items():
            sequences.setdefault(name, set()).add(values)
    string_table = {
        name: next(iter(values))
        for name, values in strings.items()
        if len(values) == 1
    }
    sequence_table = {
        name: next(iter(values))
        for name, values in sequences.items()
        if len(values) == 1
    }
    return string_table, sequence_table


def _resolve_text(node, scope, strings):
    """Resolve an expression to a literal string, or ``None``."""

    if node is None:
        return None
    if isinstance(node, ast.Name) and node.id in scope:
        return scope[node.id]
    value = _constant_arg(node)
    if value is not None:
        return value
    if isinstance(node, ast.Name):
        return strings.get(node.id)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _resolve_text(node.left, scope, strings)
        right = _resolve_text(node.right, scope, strings)
        if left is not None and right is not None:
            return left + right
    return None


def _resolve_sequence(node, scope, strings, sequences):
    """Resolve an expression to a tuple of literal strings, or ``None``."""

    if isinstance(node, (ast.Tuple, ast.List)):
        items = [_resolve_text(element, scope, strings) for element in node.elts]
        if items and all(item is not None for item in items):
            return tuple(items)
        return None
    if isinstance(node, ast.Name):
        if node.id in scope:
            return None
        return sequences.get(node.id)
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


def _iter_calls(tree, strings, sequences):
    """Yield ``(call, class_name, scope)`` for every call in the module.

    ``scope`` maps a ``for`` loop variable to each value of a constant
    sequence, so ``for header in COLUMN_HEADERS: self.tr(header)`` expands to
    every header.
    """

    def visit(node, class_name, scope):
        if isinstance(node, ast.ClassDef):
            for child in node.body:
                yield from visit(child, node.name, {})
            return
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for child in node.body:
                yield from visit(child, class_name, {})
            return
        if isinstance(node, ast.For) and isinstance(node.target, ast.Name):
            values = _resolve_sequence(node.iter, scope, strings, sequences)
            if values:
                for value in values:
                    inner = dict(scope)
                    inner[node.target.id] = value
                    for child in node.body:
                        yield from visit(child, class_name, inner)
                for child in node.orelse:
                    yield from visit(child, class_name, scope)
                return
        if isinstance(node, ast.Call):
            yield node, class_name, scope
        for child in ast.iter_child_nodes(node):
            yield from visit(child, class_name, scope)

    yield from visit(tree, None, {})


def scan(root="anylabeling") -> ScanResult:
    """Return every resolvable translatable string under ``root``."""

    root_path = Path(root)
    paths = list(_iter_python_files(root_path))
    strings, sequences = _build_project_tables(paths)
    entries = []
    unresolved = []
    for path in paths:
        relative = path.as_posix()
        source_text = path.read_text(encoding="utf-8")
        tree = ast.parse(source_text, filename=str(path))
        tr_context, helper_context = _module_contexts(tree)
        for call, class_name, scope in _iter_calls(tree, strings, sequences):
            _collect_call(
                call,
                relative,
                class_name,
                scope,
                tr_context,
                helper_context,
                strings,
                entries,
                unresolved,
            )
    entries.sort(key=lambda entry: (entry.path, entry.line, entry.text))
    return ScanResult(entries=entries, unresolved=unresolved)


def _collect_call(
    call,
    relative,
    class_name,
    scope,
    tr_context,
    helper_context,
    strings,
    entries,
    unresolved,
):
    name, receiver = _call_name(call)
    if name is None:
        return
    line = getattr(call, "lineno", 0)

    if name in TRANSLATE_NAMES or name in NOOP_NAMES:
        if len(call.args) < 2:
            return
        context = _resolve_text(call.args[0], scope, strings)
        text = _resolve_text(call.args[1], scope, strings)
        if text is None:
            return
        if context is None:
            unresolved.append((relative, line, f"{name}(context=?)"))
            return
        entries.append(Entry(relative, line, context, text))
        return

    if name not in TR_NAMES or not call.args:
        return
    text = _resolve_text(call.args[0], scope, strings)
    if text is None:
        return

    if name == "_tr":
        receiver_name = _receiver_label(receiver)
        if receiver is not None and receiver_name != "self":
            # ``host.label_manager_widget._tr(...)`` delegates to the owner
            # module, which registers the same string itself.
            return
        context = helper_context or class_name or tr_context
        if context is None:
            unresolved.append((relative, line, "_tr without context"))
            return
        entries.append(Entry(relative, line, context, text))
        return

    receiver_name = _receiver_label(receiver)
    if receiver_name == "self" and class_name is not None:
        entries.append(Entry(relative, line, class_name, text))
        return
    if tr_context:
        entries.append(Entry(relative, line, tr_context, text))
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
    r"<translation(?P<attrs>[^>]*?)(?:/>|>(?P<body>.*?)</translation>)",
    flags=re.DOTALL,
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
        attributes = translation_match.group("attrs")
        body = translation_match.group("body") or ""
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


def fill_identity(ts_path) -> int:
    """Use the source text as the translation for empty messages.

    ``en_US`` is the extraction language: every new message must still carry a
    translation, otherwise ``lrelease`` drops it and the English UI falls back
    to the source only by accident.  Identity translations are also legitimate
    for proper nouns in the other languages, so this helper is generic; the
    generator calls it for ``en_US`` only.
    """

    text = Path(ts_path).read_text(encoding="utf-8")
    filled = 0

    def replace_block(match):
        nonlocal filled
        block = match.group(0)
        source_match = re.search(
            r"<source>(.*?)</source>", block, flags=re.DOTALL
        )
        translation_match = _TRANSLATION.search(block)
        if source_match is None or translation_match is None:
            return block
        attributes = translation_match.group("attrs")
        body = translation_match.group("body") or ""
        if body.strip() and 'type="unfinished"' not in attributes:
            return block
        filled += 1
        source = _unescape(source_match.group(1))
        return (
            block[: translation_match.start()]
            + f"<translation>{escape(source)}</translation>"
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
