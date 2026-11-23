"""Parse category names pasted by the user (fork.40).

Category names are separated by an English/Chinese comma, spaces, or newlines.
The parser is Qt-free so the import rule can be tested without a window.
"""

import re


_SEPARATORS = re.compile(r"[,，\s]+")


def parse_category_names(text):
    """Return unique non-empty names in input order."""
    if not isinstance(text, str):
        return []
    names = []
    seen = set()
    for part in _SEPARATORS.split(text.strip()):
        name = part.strip()
        if name and name not in seen:
            seen.add(name)
            names.append(name)
    return names
