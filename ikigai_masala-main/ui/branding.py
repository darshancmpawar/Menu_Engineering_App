"""Brand assets helper — surfaces the SmartQ logo if one is present.

Drop ``smartq_logo.svg`` / ``smartq_logo.png`` into ``ui/assets/`` (see the
README there) and it lights up in the sidebar, the editor header, and the
browser-tab favicon. Everything degrades gracefully to the default emoji mark
when no file is present, so the app never breaks on a missing asset.
"""

from __future__ import annotations

import base64
import os
from functools import lru_cache
from typing import Optional

_ASSETS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")

# Default emoji mark used when no logo file is present (curry rice).
DEFAULT_ICON_URL = (
    "https://em-content.zobj.net/source/apple/391/curry-rice_1f35b.png"
)


def logo_path(raster_only: bool = False) -> Optional[str]:
    """Return the path to the logo file, or None if absent.

    ``raster_only`` restricts to PNG (used for the favicon, where a raster
    image is the most portable).
    """
    names = ("smartq_logo.png",) if raster_only else ("smartq_logo.svg", "smartq_logo.png")
    for name in names:
        p = os.path.join(_ASSETS_DIR, name)
        if os.path.isfile(p):
            return p
    return None


@lru_cache(maxsize=2)
def _logo_data_uri() -> Optional[str]:
    p = logo_path()
    if not p:
        return None
    mime = "image/svg+xml" if p.endswith(".svg") else "image/png"
    with open(p, "rb") as f:
        enc = base64.b64encode(f.read()).decode("ascii")
    return f"data:{mime};base64,{enc}"


def logo_img_tag(height: int = 32, alt: str = "SmartQ", extra_style: str = "") -> str:
    """Return an ``<img>`` tag (data URI) for the logo, or "" if no file."""
    uri = _logo_data_uri()
    if not uri:
        return ""
    return (
        f'<img src="{uri}" alt="{alt}" '
        f'style="height:{height}px;width:auto;display:block;{extra_style}">'
    )


def favicon():
    """Return a value suitable for ``st.set_page_config(page_icon=...)``:
    the PNG logo path if present, else the default emoji image URL."""
    return logo_path(raster_only=True) or DEFAULT_ICON_URL
