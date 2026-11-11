r"""Search syntax for the file list.

The module turns the text typed into the search box into a query that is
evaluated against image file names and their annotation JSON files.

Grammar (all operators work for every field and can be freely combined)
-----------------------------------------------------------------------
``field::value``
    A condition.  Supported fields are ``label``, ``split``, ``shape``,
    ``type``, ``gid``, ``difficult``, ``checked``, ``review``, ``score`` and
    ``description``.  The field name is case insensitive.

``plain text``
    Any token that is not ``field::value`` is matched as a case sensitive
    substring of the image file name (the historical behaviour).

``,``
    Logical AND.  It binds tighter than ``|``.

``|``
    Logical OR.

``!``
    Prefix negation, applies to the condition or parenthesised group that
    follows (``!!x`` is a double negation).

``( )``
    Grouping, overrides the default precedence.

Escaping
--------
A backslash escapes the next character, which allows literal separators in
values: ``label::a\,b`` matches the single label ``a,b``, ``label::a\|b`` the
single label ``a|b`` and ``label::a\\b`` the label ``a\b``.  Escaping also
applies to plain text tokens (``foo\ bar`` searches for ``foo bar``).

Same field multi-value shorthand
--------------------------------
``label::cat|dog`` is the same as ``label::cat|label::dog`` (any of the labels),
``label::cat,dog`` requires the file to contain both labels.  This expansion
happens before the normal precedence rules are applied, so ``|`` and ``,`` keep
their meaning: ``label::cat|dog,split::train`` is
``label::cat | (label::dog , split::train)``.  The shorthand also works for
``type``, ``split`` and every other field.

Special values
--------------
``split`` accepts ``none``/``train``/``val``/``test`` and the Chinese aliases
``未划分``/``训练``/``验证``/``测试``.  ``shape::1``/``shape::0`` mean "has
objects" / "has no objects".  ``checked`` accepts ``passed``/``failed``/
``unchecked`` or a boolean-ish value.  ``score`` accepts a range such as
``[0,0.5]`` or ``(0,0.6]``.

Legacy syntax
-------------
``#N`` selects the N-th imported image, ``<regex>`` searches the file name with
a regular expression and the single condition forms used before this module was
rewritten (``checked::1``, ``label::person``, ``gid::0`` ...) keep working.
:func:`parse_search_pattern`, :func:`matches_filename` and
:func:`matches_label_attribute` are kept for existing callers.

Missing annotation files are treated as "no objects / split none / unchecked"
when a query is evaluated.
"""

import json
import os
import os.path as osp
import re
from typing import Dict, Optional

# -- split values -------------------------------------------------------

SPLIT_NONE = "none"
SPLIT_TRAIN = "train"
SPLIT_VAL = "val"
SPLIT_TEST = "test"

SPLIT_KEYS = (SPLIT_NONE, SPLIT_TRAIN, SPLIT_VAL, SPLIT_TEST)

#: Aliases accepted for ``split::`` values.  Keys are compared lower case.
_SPLIT_VALUE_ALIASES = {
    "none": SPLIT_NONE,
    "unpartitioned": SPLIT_NONE,
    "未划分": SPLIT_NONE,
    "无划分": SPLIT_NONE,
    "train": SPLIT_TRAIN,
    "training": SPLIT_TRAIN,
    "训练": SPLIT_TRAIN,
    "val": SPLIT_VAL,
    "valid": SPLIT_VAL,
    "validation": SPLIT_VAL,
    "验证": SPLIT_VAL,
    "test": SPLIT_TEST,
    "testing": SPLIT_TEST,
    "测试": SPLIT_TEST,
}

#: Fields understood by ``field::value`` conditions.
_SEARCH_FIELDS = frozenset(
    (
        "label",
        "split",
        "shape",
        "type",
        "gid",
        "difficult",
        "checked",
        "review",
        "score",
        "description",
    )
)

_REVIEW_STATUSES = frozenset(("pending", "missed", "false_positive"))
_CHECKED_STATUSES = frozenset(("passed", "failed", "unchecked"))
_TRUE_VALUES = frozenset(("true", "1", "yes"))

_INDEX_RE = re.compile(r"^#(\d+)$")

#: Characters escaped by :func:`escape_query_value` in addition to whitespace
#: at the beginning/end of a value.
_ESCAPE_CHARS = frozenset("\\,|()!:<>")


class SearchQueryError(ValueError):
    """Raised internally when query text cannot be parsed.

    The public parser never propagates it: unparsable text is treated as a
    literal file-name search so that old free-text searches keep working.
    """


# -- annotation data ----------------------------------------------------


class _LabelData:
    """Normalised view of one annotation JSON file.

    ``exists`` tells whether the file could be read and decoded.  Every field
    is filled with the "missing file" default when it could not be read, so
    :class:`SearchQuery` can use a single code path for missing files.
    """

    __slots__ = ("data", "exists", "shapes", "split", "checked")

    def __init__(self, data=None):
        self.data = data if isinstance(data, dict) else None
        self.exists = self.data is not None
        if not self.exists:
            self.shapes = []
            self.split = SPLIT_NONE
            self.checked = False
            return

        shapes = self.data.get("shapes")
        self.shapes = shapes if isinstance(shapes, list) else []
        self.split = _normalize_stored_split(self.data.get("split"))
        self.checked = self.data.get("checked", False)


def _normalize_stored_split(value):
    """Normalise a ``split`` value read from an annotation file."""
    if isinstance(value, str):
        return _SPLIT_VALUE_ALIASES.get(value.strip().lower(), SPLIT_NONE)
    return SPLIT_NONE


def _parse_split_query(value):
    """Parse a ``split::`` query value, raising :class:`SearchQueryError`."""
    if isinstance(value, str):
        split = _SPLIT_VALUE_ALIASES.get(value.strip().lower())
        if split is not None:
            return split
    raise SearchQueryError(f"unsupported split value: {value!r}")


def _as_bool(value):
    return str(value).strip().lower() in _TRUE_VALUES


def _read_label_json(label_file):
    try:
        with open(label_file, "r", encoding="utf-8") as stream:
            return json.load(stream)
    except (OSError, ValueError, TypeError):
        return None


def _load_label_data(label_file, cache=None):
    """Load ``label_file`` once per (path, mtime), using ``cache`` if given."""
    if not label_file:
        return _LabelData(None)

    path = _to_text(label_file)
    try:
        mtime = os.path.getmtime(path)
    except (OSError, ValueError):
        mtime = None

    if cache is not None:
        cached = cache.get(path)
        if cached is not None and cached[0] == mtime:
            return cached[1]

    data = _read_label_json(path) if mtime is not None else None
    label_data = _LabelData(data)
    if cache is not None:
        cache[path] = (mtime, label_data)
    return label_data


def _to_text(value):
    try:
        path = os.fspath(value)
    except TypeError:
        path = value
    if isinstance(path, bytes):
        return os.fsdecode(path)
    if isinstance(path, str):
        return path
    return str(path)


def _shape_iter(label_data):
    """Yield dict-like shapes of ``label_data``."""
    for shape in label_data.shapes:
        if isinstance(shape, dict):
            yield shape


# -- query nodes --------------------------------------------------------


class _Node:
    """Base class of the boolean expression tree."""

    __slots__ = ()

    def matches(self, image_file, label_data):  # pragma: no cover - interface
        raise NotImplementedError


class _AndNode(_Node):
    __slots__ = ("left", "right")

    def __init__(self, left, right):
        self.left = left
        self.right = right

    def matches(self, image_file, label_data):
        return self.left.matches(image_file, label_data) and self.right.matches(
            image_file, label_data
        )


class _OrNode(_Node):
    __slots__ = ("left", "right")

    def __init__(self, left, right):
        self.left = left
        self.right = right

    def matches(self, image_file, label_data):
        return self.left.matches(image_file, label_data) or self.right.matches(
            image_file, label_data
        )


class _NotNode(_Node):
    __slots__ = ("child",)

    def __init__(self, child):
        self.child = child

    def matches(self, image_file, label_data):
        return not self.child.matches(image_file, label_data)


class _FilenameNode(_Node):
    """Case sensitive substring match against the image file name."""

    __slots__ = ("text",)

    def __init__(self, text):
        self.text = text

    def matches(self, image_file, label_data):
        return self.text in _to_text(image_file)


class _RegexNode(_Node):
    __slots__ = ("regex",)

    def __init__(self, regex):
        self.regex = regex

    def matches(self, image_file, label_data):
        return bool(self.regex.search(_to_text(image_file)))


class _AttributeNode(_Node):
    """A single ``field::value`` condition.

    The raw value is normalised by :func:`_make_attribute_node`; :attr:`spec`
    holds the ready-to-compare value (bool, int, str, split key or score
    range).
    """

    __slots__ = ("field", "spec")

    def __init__(self, field, spec):
        self.field = field
        self.spec = spec

    # -- missing / unreadable annotation files -------------------------
    def _matches_missing(self):
        field = self.field
        if field == "shape":
            return self.spec is False
        if field == "split":
            return self.spec == SPLIT_NONE
        if field == "checked":
            return self.spec is False or self.spec == "unchecked"
        return False

    def matches(self, image_file, label_data):
        if not label_data.exists:
            return self._matches_missing()

        field = self.field
        spec = self.spec

        if field == "shape":
            return (len(label_data.shapes) > 0) == spec
        if field == "split":
            return label_data.split == spec
        if field == "checked":
            return _matches_checked(label_data.checked, spec)
        if field == "label":
            return _matches_label(label_data, spec)
        if field == "type":
            return _matches_shape_type(label_data, spec)
        if field == "gid":
            return _matches_gid(label_data, spec)
        if field == "difficult":
            return _matches_difficult(label_data, spec)
        if field == "review":
            return any(
                shape.get("review_status", "pending") == spec
                for shape in _shape_iter(label_data)
            )
        if field == "score":
            return _matches_score(label_data, spec)
        if field == "description":
            return _matches_description(label_data, spec)
        return False


def _matches_checked(checked, spec):
    if spec == "passed":
        return checked is True
    if spec == "failed":
        return checked == "failed"
    if spec == "unchecked":
        return checked is not True and checked != "failed"
    return (checked is True or checked == "failed") == spec


def _matches_label(label_data, spec):
    if not isinstance(spec, str) or not spec:
        return False
    target = spec.lower()
    for shape in _shape_iter(label_data):
        label = shape.get("label", "")
        if isinstance(label, str) and label and label.lower() == target:
            return True
    return False


def _matches_shape_type(label_data, spec):
    if not isinstance(spec, str) or not spec:
        return False
    target = spec.lower()
    for shape in _shape_iter(label_data):
        shape_type = shape.get("shape_type", "")
        if (
            isinstance(shape_type, str)
            and shape_type
            and shape_type.lower() == target
        ):
            return True
    return False


def _matches_gid(label_data, spec):
    for shape in _shape_iter(label_data):
        group_id = shape.get("group_id", -1)
        if group_id is not None and group_id == spec:
            return True
    return False


def _matches_difficult(label_data, spec):
    for shape in _shape_iter(label_data):
        if "difficult" not in shape:
            continue
        shape_value = shape["difficult"]
        if isinstance(shape_value, bool):
            if shape_value == spec:
                return True
        elif isinstance(shape_value, str):
            if (shape_value.strip().lower() in _TRUE_VALUES) == spec:
                return True
        elif isinstance(shape_value, (int, float)):
            if bool(shape_value) == spec:
                return True
    return False


def _matches_score(label_data, spec):
    min_value = spec["min"]
    max_value = spec["max"]
    min_inclusive = spec["min_inclusive"]
    max_inclusive = spec["max_inclusive"]
    for shape in _shape_iter(label_data):
        score = shape.get("score", 0.0)
        if not isinstance(score, (int, float)) or isinstance(score, bool):
            continue
        score = float(score)
        min_match = (
            score >= min_value if min_inclusive else score > min_value
        )
        max_match = (
            score <= max_value if max_inclusive else score < max_value
        )
        if min_match and max_match:
            return True
    return False


def _matches_description(label_data, spec):
    for shape in _shape_iter(label_data):
        description = shape.get("description", "")
        if isinstance(description, str):
            has_description = bool(description and description.strip())
        else:
            has_description = bool(description)
        if has_description == spec:
            return True
    return False


def _make_attribute_node(field, raw_value):
    """Build an :class:`_AttributeNode` from a raw ``field::value`` value."""
    if field not in _SEARCH_FIELDS:
        raise SearchQueryError(f"unknown search field: {field!r}")

    if field in ("label", "type"):
        return _AttributeNode(field, raw_value)
    if field == "split":
        return _AttributeNode(field, _parse_split_query(raw_value))
    if field == "shape":
        return _AttributeNode(field, _as_bool(raw_value))
    if field == "difficult":
        return _AttributeNode(field, _as_bool(raw_value))
    if field == "description":
        return _AttributeNode(field, _as_bool(raw_value))
    if field == "gid":
        try:
            return _AttributeNode(field, int(str(raw_value).strip()))
        except (TypeError, ValueError):
            raise SearchQueryError(f"invalid gid value: {raw_value!r}")
    if field == "checked":
        status = str(raw_value).strip().lower()
        if status in _CHECKED_STATUSES:
            return _AttributeNode(field, status)
        return _AttributeNode(field, _as_bool(status))
    if field == "review":
        status = str(raw_value).strip().lower()
        if status not in _REVIEW_STATUSES:
            raise SearchQueryError(f"invalid review value: {raw_value!r}")
        return _AttributeNode(field, status)
    # score
    score_range = _parse_score_range(str(raw_value))
    if not score_range:
        raise SearchQueryError(f"invalid score range: {raw_value!r}")
    return _AttributeNode(field, score_range)


# -- parsing ------------------------------------------------------------


def _unescape(text):
    """Remove one level of backslash escaping from ``text``."""
    result = []
    index = 0
    length = len(text)
    while index < length:
        char = text[index]
        if char == "\\":
            if index + 1 < length:
                result.append(text[index + 1])
                index += 2
                continue
            result.append("\\")
            index += 1
            continue
        result.append(char)
        index += 1
    return "".join(result)


def _trim_raw_value(raw):
    """Strip unescaped whitespace from both ends of a raw (escaped) value."""
    start = 0
    end = len(raw)
    while start < end and raw[start].isspace():
        start += 1
    while end > start and raw[end - 1].isspace():
        backslashes = 0
        cursor = end - 2
        while cursor >= start and raw[cursor] == "\\":
            backslashes += 1
            cursor -= 1
        if backslashes % 2 == 1:
            break
        end -= 1
    return raw[start:end]


class _QueryParser:
    """Recursive descent parser producing a boolean expression tree."""

    _DELIMITERS = frozenset(",|()")

    def __init__(self, text):
        self.text = text
        self.tokens = []
        self.cursor = 0
        self._implied_fields = [None]
        self._position = 0

    # -- tokenizer ------------------------------------------------------
    def tokenize(self):
        text = self.text
        length = len(text)
        position = 0
        expect_operand = True

        while True:
            while position < length and text[position].isspace():
                position += 1
            if position >= length:
                if self.tokens and self.tokens[-1][0] in (
                    "AND",
                    "OR",
                    "NOT",
                    "LP",
                ):
                    raise SearchQueryError("dangling operator")
                return

            char = text[position]

            if expect_operand:
                if char == "(":
                    self.tokens.append(("LP", None))
                    self._implied_fields.append(None)
                    position += 1
                    continue
                if char == ")":
                    raise SearchQueryError("unexpected ')'")
                if char == "!":
                    self.tokens.append(("NOT", None))
                    position += 1
                    continue
                if char in ",|":
                    raise SearchQueryError("unexpected operator")
                node, position, field = self._parse_operand(position)
                self.tokens.append(("ATOM", node))
                self._implied_fields[-1] = field
                expect_operand = False
                continue

            if char == ",":
                self.tokens.append(("AND", None))
                position += 1
                expect_operand = True
                continue
            if char == "|":
                self.tokens.append(("OR", None))
                position += 1
                expect_operand = True
                continue
            if char == ")":
                if len(self._implied_fields) == 1:
                    raise SearchQueryError("unbalanced ')'")
                self.tokens.append(("RP", None))
                self._implied_fields.pop()
                self._implied_fields[-1] = None
                position += 1
                continue
            raise SearchQueryError("missing operator")

    # -- operands -------------------------------------------------------
    def _parse_operand(self, position):
        text = self.text
        implied_field = self._implied_fields[-1]

        if implied_field is None and text[position] == "<":
            return self._parse_regex(position)

        separator = self._find_field_separator(position)
        if separator >= 0:
            field = text[position:separator].strip().lower()
            if not field:
                raise SearchQueryError("empty field name")
            value, position = self._scan_field_value(separator + 2, field)
            return _make_attribute_node(field, value), position, field

        if implied_field is not None:
            value, position = self._scan_field_value(position, implied_field)
            return (
                _make_attribute_node(implied_field, value),
                position,
                implied_field,
            )

        raw, position = self._scan_plain_text(position)
        value = _unescape(_trim_raw_value(raw))
        if not value:
            raise SearchQueryError("empty search text")
        return _FilenameNode(value), position, None

    def _find_field_separator(self, position):
        text = self.text
        length = len(text)
        while position < length:
            char = text[position]
            if char == "\\":
                position += 2
                continue
            if char == ":" and position + 1 < length and text[position + 1] == ":":
                return position
            if char in self._DELIMITERS:
                return -1
            position += 1
        return -1

    def _scan_field_value(self, position, field):
        text = self.text
        length = len(text)
        while position < length and text[position].isspace():
            position += 1
        if position >= length:
            return "", position

        # Score ranges contain natural commas: "score::[0,0.5]".
        if field == "score" and text[position] in "[(":
            cursor = position + 1
            while cursor < length and text[cursor] not in "])":
                cursor += 1
            if cursor >= length:
                raise SearchQueryError("unterminated score range")
            return text[position : cursor + 1], cursor + 1

        start = position
        while position < length:
            char = text[position]
            if char == "\\":
                position += 2
                continue
            if char in ",|)":
                break
            position += 1
        raw = text[start:position]
        return _unescape(_trim_raw_value(raw)), position

    def _scan_plain_text(self, position):
        text = self.text
        length = len(text)
        start = position
        while position < length:
            char = text[position]
            if char == "\\":
                position += 2
                continue
            if char in self._DELIMITERS:
                break
            position += 1
        return text[start:position], position

    def _parse_regex(self, position):
        text = self.text
        length = len(text)
        cursor = position + 1
        while cursor < length:
            char = text[cursor]
            if char == "\\":
                cursor += 2
                continue
            if char == ">":
                break
            cursor += 1
        if cursor >= length:
            raise SearchQueryError("unterminated regular expression")
        body = text[position + 1 : cursor]
        if not body:
            raise SearchQueryError("empty regular expression")
        try:
            regex = re.compile(body, re.IGNORECASE)
        except re.error:
            raise SearchQueryError(f"invalid regular expression: {body!r}")
        return _RegexNode(regex), cursor + 1, None

    # -- expression tree ------------------------------------------------
    def parse(self):
        self.tokenize()
        node = self._parse_or()
        if self.cursor != len(self.tokens):
            raise SearchQueryError("unexpected token")
        if len(self._implied_fields) != 1:
            raise SearchQueryError("unclosed group")
        return node

    def _peek(self):
        if self.cursor < len(self.tokens):
            return self.tokens[self.cursor][0]
        return None

    def _parse_or(self):
        node = self._parse_and()
        while self._peek() == "OR":
            self.cursor += 1
            node = _OrNode(node, self._parse_and())
        return node

    def _parse_and(self):
        node = self._parse_unary()
        while self._peek() == "AND":
            self.cursor += 1
            node = _AndNode(node, self._parse_unary())
        return node

    def _parse_unary(self):
        if self._peek() == "NOT":
            self.cursor += 1
            return _NotNode(self._parse_unary())
        return self._parse_primary()

    def _parse_primary(self):
        token = self._peek()
        if token == "ATOM":
            node = self.tokens[self.cursor][1]
            self.cursor += 1
            return node
        if token == "LP":
            self.cursor += 1
            node = self._parse_or()
            if self._peek() != "RP":
                raise SearchQueryError("unclosed group")
            self.cursor += 1
            return node
        raise SearchQueryError("expected a condition")


# -- public query object ------------------------------------------------


class SearchQuery:
    """A parsed search query.

    Use :func:`parse_search_query` to build one and :meth:`matches` to test an
    image file.  A query keeps a short-lived cache of parsed annotation files.
    """

    def __init__(self, node=None, index=None, text=""):
        self._node = node
        self._index = index
        self.text = text
        self._cache = {}

    # -- introspection --------------------------------------------------
    @property
    def node(self):
        """Root of the boolean expression tree (``None`` means match all)."""
        return self._node

    @property
    def index(self):
        """1-based image index for ``#N`` queries, otherwise ``None``."""
        return self._index

    @property
    def is_index(self):
        return self._index is not None

    @property
    def matches_all(self):
        return self._node is None and self._index is None

    def __repr__(self):
        return f"SearchQuery(text={self.text!r}, index={self._index!r})"

    # -- evaluation -----------------------------------------------------
    def matches(self, image_file, label_file=None):
        """Return whether ``image_file`` matches this query.

        ``label_file`` is the annotation JSON path; when omitted it is derived
        from ``image_file``.  A missing or unreadable annotation file is
        treated as "no objects / split none / unchecked".
        """
        if self._index is not None:
            # Index queries are positional and only make sense for a list of
            # files; see :func:`filter_image_files`.
            return True
        if self._node is None:
            return True
        if label_file is None:
            label_file = _default_label_file(image_file)
        label_data = _load_label_data(label_file, self._cache)
        return bool(self._node.matches(image_file, label_data))


def _default_label_file(image_file):
    path = _to_text(image_file)
    return osp.splitext(path)[0] + ".json"


def parse_search_query(search_text) -> SearchQuery:
    """Parse ``search_text`` into a :class:`SearchQuery`.

    Empty/whitespace-only text matches everything.  Text that cannot be parsed
    (unknown field, invalid value, unbalanced parentheses ...) falls back to a
    literal file-name substring search, which preserves the historical
    behaviour for free text.
    """
    if search_text is None:
        return SearchQuery(text="")
    text = _trim_raw_value(_to_text(search_text))
    if not text:
        return SearchQuery(text="")

    match = _INDEX_RE.match(text)
    if match is not None:
        index = int(match.group(1))
        if index > 0:
            return SearchQuery(index=index, text=text)

    try:
        node = _QueryParser(text).parse()
    except SearchQueryError:
        node = _FilenameNode(text)
    return SearchQuery(node=node, text=text)


# -- query helpers ------------------------------------------------------


def escape_query_value(text) -> str:
    """Escape ``text`` so it can be embedded as a ``field::value`` value.

    The returned string is safe to insert after ``field::``: separators
    (``,`` ``|`` ``(`` ``)`` ...) and leading/trailing whitespace are
    backslash-escaped.  ``text`` is converted with :func:`str`.
    """
    value = _to_text(text)
    result = []
    for char in value:
        if char in _ESCAPE_CHARS:
            result.append("\\")
        result.append(char)
    escaped = "".join(result)

    if escaped and escaped[0].isspace():
        escaped = "\\" + escaped
    if escaped and escaped[-1].isspace():
        escaped = escaped[:-1] + "\\" + escaped[-1]
    return escaped


def escape_search_text(text) -> str:
    """Alias of :func:`escape_query_value` for plain search text."""
    return escape_query_value(text)


# -- legacy compatibility ----------------------------------------------


class SearchPattern:
    """Represents a parsed search pattern (legacy interface).

    ``mode`` keeps its historical values (``normal``, ``regex``, ``index``,
    ``attribute``).  Compound boolean queries use the new ``query`` mode; all
    modes can be evaluated with :func:`filter_image_files`, which prefers the
    attached :class:`SearchQuery`.
    """

    def __init__(
        self,
        mode: str,
        pattern: Optional[str] = None,
        regex: Optional[re.Pattern] = None,
        attribute_filter: Optional[Dict] = None,
        index: Optional[int] = None,
        query: Optional[SearchQuery] = None,
    ):
        self.mode = mode
        self.pattern = pattern
        self.regex = regex
        self.attribute_filter = attribute_filter
        self.index = index
        self.query = query


def parse_search_pattern(search_text: str) -> SearchPattern:
    """
    Parse search text into a legacy :class:`SearchPattern` object.

    The returned pattern keeps the historical ``mode`` values for old syntaxes
    while the new boolean syntax is available through the attached
    ``pattern.query`` and through :func:`filter_image_files`.

    Examples:
        - "test" -> normal text search
        - "#1" -> index search for the first image
        - "<\\.png$>" -> regex search
        - "difficult::1" -> attribute search for difficult objects
        - "gid::0" / "gid::1" -> attribute search by group id
        - "shape::1" -> files with any shapes
        - "label::person" -> files with label "person"
        - "type::rectangle" -> files with shape_type "rectangle"
        - "split::val" -> files assigned to the "val" split
        - "score::[0,0.5]" -> files with score in [0, 0.5]
        - "score::(0,0.6]" -> files with score in (0, 0.6]
        - "description::1" -> files with a non-empty description
        - "checked::1" -> checked files
        - "label::cat|dog" -> files with cat or dog (mode "query")
    """
    query = parse_search_query(search_text)
    if query.matches_all:
        return SearchPattern(mode="normal", pattern=None, query=query)
    if query.is_index:
        return SearchPattern(mode="index", index=query.index, query=query)

    node = query.node
    if isinstance(node, _RegexNode):
        return SearchPattern(mode="regex", regex=node.regex, query=query)
    if isinstance(node, _AttributeNode):
        return SearchPattern(
            mode="attribute",
            attribute_filter=_legacy_attribute_filter(node),
            query=query,
        )
    if isinstance(node, _FilenameNode):
        return SearchPattern(
            mode="normal", pattern=node.text, query=query
        )
    return SearchPattern(
        mode="query", pattern=query.text, query=query
    )


def _legacy_attribute_filter(node):
    """Convert an attribute node back to the historical filter dict."""
    return {"type": node.field, "value": node.spec}


def _pattern_to_query(search_pattern):
    """Build a :class:`SearchQuery` for a legacy :class:`SearchPattern`."""
    query = getattr(search_pattern, "query", None)
    if query is not None:
        return query

    mode = search_pattern.mode
    if mode == "index":
        return SearchQuery(index=search_pattern.index)
    if mode == "regex":
        if search_pattern.regex is None:
            return SearchQuery(node=_FilenameNode("\0"))
        return SearchQuery(node=_RegexNode(search_pattern.regex))
    if mode == "normal":
        if not search_pattern.pattern:
            return SearchQuery()
        return SearchQuery(node=_FilenameNode(search_pattern.pattern))
    if mode == "attribute" and search_pattern.attribute_filter:
        attribute_filter = search_pattern.attribute_filter
        field = str(attribute_filter.get("type", "")).lower()
        value = attribute_filter.get("value")
        try:
            if field == "score" and isinstance(value, dict):
                node = _AttributeNode("score", value)
            else:
                node = _make_attribute_node(field, value)
        except SearchQueryError:
            return SearchQuery(node=_FilenameNode("\0"))
        return SearchQuery(node=node)
    if mode == "query" and search_pattern.pattern:
        return parse_search_query(search_pattern.pattern)
    return SearchQuery()


def _query_from_any(query_or_pattern):
    if query_or_pattern is None:
        return SearchQuery()
    if isinstance(query_or_pattern, SearchQuery):
        return query_or_pattern
    if isinstance(query_or_pattern, SearchPattern):
        return _pattern_to_query(query_or_pattern)
    if isinstance(query_or_pattern, str):
        return parse_search_query(query_or_pattern)
    raise TypeError(
        "expected a SearchQuery, SearchPattern or str, got "
        f"{type(query_or_pattern).__name__}"
    )


def _label_file_for(image_file, output_dir=None):
    label_file = osp.splitext(_to_text(image_file))[0] + ".json"
    if output_dir:
        label_file = osp.join(_to_text(output_dir), osp.basename(label_file))
    return label_file


def matches_filename(filename: str, search_pattern: SearchPattern) -> bool:
    """
    Check if filename matches the search pattern (legacy interface).

    Only the file-name part of the pattern is evaluated here.  Prefer
    :meth:`SearchQuery.matches` (or :func:`filter_image_files`) when the query
    may contain ``field::value`` conditions.
    """
    mode = getattr(search_pattern, "mode", None)
    if mode == "regex":
        if search_pattern.regex:
            return bool(search_pattern.regex.search(_to_text(filename)))
        return False
    if mode == "normal":
        if search_pattern.pattern:
            return search_pattern.pattern in _to_text(filename)
        return True
    return True


def matches_label_attribute(
    image_file: str,
    label_file: str,
    search_pattern: SearchPattern,
) -> bool:
    """
    Check if label file contains shapes matching the attribute filter.

    Legacy interface kept for existing callers.  For ``attribute`` patterns it
    evaluates the full query attached to ``search_pattern`` when available
    (which also covers compound queries), otherwise it falls back to the legacy
    ``attribute_filter`` dict.  Non-attribute patterns return ``True`` as
    before.
    """
    mode = getattr(search_pattern, "mode", None)
    if mode not in ("attribute", "query"):
        return True

    query = _pattern_to_query(search_pattern)
    if query.matches_all:
        return True
    if query.is_index:
        return True
    label_data = _load_label_data(label_file)
    return bool(query.node.matches(image_file, label_data))


def filter_image_files(
    image_files: list,
    search_pattern,
    output_dir: Optional[str] = None,
) -> list:
    """
    Filter image files based on a search query.

    Args:
        image_files: List of image file paths.
        search_pattern: A :class:`SearchQuery`, a legacy
            :class:`SearchPattern`, or raw query text.
        output_dir: Optional output directory for label files.

    Returns:
        Filtered list of image files.
    """
    query = _query_from_any(search_pattern)

    if query.is_index:
        target_index = query.index - 1
        if target_index < 0 or target_index >= len(image_files):
            return []
        return [image_files[target_index]]

    if query.matches_all:
        return list(image_files)

    filtered_files = []
    for filename in image_files:
        label_file = _label_file_for(filename, output_dir)
        if query.matches(filename, label_file):
            filtered_files.append(filename)
    return filtered_files


# -- score ranges -------------------------------------------------------


def _parse_score_range(range_str: str) -> Optional[Dict]:
    """
    Parse score range string into a dictionary.

    Args:
        range_str: Range string like "[0,0.5]", "(0,0.6]", "[0,0.6)", "(0,0.6)"

    Returns:
        Dictionary with 'min', 'max', 'min_inclusive', 'max_inclusive' keys,
        or None if parsing fails.
    """
    range_str = str(range_str).strip()
    if not range_str:
        return None

    if len(range_str) < 5:
        return None

    left_bracket = range_str[0]
    right_bracket = range_str[-1]

    if left_bracket not in ("[", "(") or right_bracket not in ("]", ")"):
        return None

    min_inclusive = left_bracket == "["
    max_inclusive = right_bracket == "]"

    content = range_str[1:-1]
    parts = content.split(",")
    if len(parts) != 2:
        return None

    try:
        min_val = float(parts[0].strip())
        max_val = float(parts[1].strip())
        if min_val > max_val:
            return None
        return {
            "min": min_val,
            "max": max_val,
            "min_inclusive": min_inclusive,
            "max_inclusive": max_inclusive,
        }
    except (ValueError, AttributeError):
        return None
