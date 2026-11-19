import re
from typing import Any, Dict, List, Optional, Union

from anylabeling.app_info import __version__

XLABEL_BASIC_FIELDS = [
    "version",
    "flags",
    "checked",
    "shapes",
    "imagePath",
    "imageData",
    "imageHeight",
    "imageWidth",
]

IMAGE_TAGS_FIELD = "tags"

#: Review status of an image: ``True``/``False`` or the string ``"failed"``.
CHECKED_FIELD = "checked"

#: Cheap JSON scan for the checked field (used before full parsing).
CHECKED_FIELD_PATTERN = re.compile(
    r'"checked"\s*:\s*(true|false|"failed")'
)


def create_xlabel_template(
    version: str = __version__,
    flags: Optional[Dict[str, Any]] = None,
    checked: Union[bool, str] = False,
    shapes: Optional[List[Dict[str, Any]]] = None,
    image_path: str = "",
    image_data: Optional[str] = None,
    image_height: int = -1,
    image_width: int = -1,
) -> Dict[str, Any]:
    return {
        "version": version,
        "flags": flags if flags is not None else {},
        "checked": checked,
        "shapes": shapes if shapes is not None else [],
        "imagePath": image_path,
        "imageData": image_data,
        "imageHeight": image_height,
        "imageWidth": image_width,
    }
