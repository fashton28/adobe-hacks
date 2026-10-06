import re
from typing import Optional, Tuple

_RGBA_RE = re.compile(
    r"rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*(?:,\s*([\d.]+)\s*)?\)"
)


def parse_rgba(
    value: Optional[str], default: Tuple[int, int, int, float] = (0, 0, 0, 1.0)
) -> Tuple[int, int, int, float]:
    """Parse a CSS-style `rgba(r,g,b,a)` / `rgb(r,g,b)` string.

    Returns `(r, g, b, a)` with `r,g,b` as 0-255 ints and `a` as a 0-1 float.
    Falls back to `default` for anything that doesn't parse.
    """
    if not value:
        return default
    match = _RGBA_RE.match(value.strip())
    if not match:
        return default
    r, g, b = (int(float(match.group(i))) for i in (1, 2, 3))
    a = float(match.group(4)) if match.group(4) is not None else 1.0
    return (r, g, b, a)
