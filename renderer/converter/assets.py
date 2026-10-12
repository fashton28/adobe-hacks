from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw


def asset_path(assets_dir: Optional[str], asset_id: Optional[str]) -> Optional[Path]:
    if not assets_dir or not asset_id:
        return None
    candidate = Path(assets_dir) / asset_id
    return candidate if candidate.is_file() else None


def load_asset_image(
    assets_dir: Optional[str],
    asset_id: Optional[str],
    width: float,
    height: float,
    fit: str = "contain",
    show_missing_assets: bool = False,
) -> Image.Image:
    """Load an asset; leave absent artwork transparent unless debugging.

    `fit` (`contain`/`cover`/`fill`, per the v0.9 schema) is emulated here
    because cr-renderer itself just stretches whatever image it's given
    into the element's box - it has no notion of aspect-preserving fit.
    """
    path = asset_path(assets_dir, asset_id)
    if path is None:
        if show_missing_assets:
            return _placeholder(asset_id, width, height)
        return Image.new("RGBA", (max(1, round(width)), max(1, round(height))), (0, 0, 0, 0))
    image = Image.open(path).convert("RGBA")
    return _fit_image(image, width, height, fit)


def _placeholder(asset_id: Optional[str], width: float, height: float) -> Image.Image:
    w, h = max(1, round(width)), max(1, round(height))
    image = Image.new("RGBA", (w, h), (214, 214, 214, 255))
    draw = ImageDraw.Draw(image)
    border = max(2, min(w, h) // 100)
    draw.rectangle([0, 0, w - 1, h - 1], outline=(150, 40, 40, 255), width=border)
    label = f"missing asset:\n{asset_id or '(none)'}"
    try:
        draw.multiline_text((w / 2, h / 2), label, fill=(120, 20, 20, 255), anchor="mm", align="center")
    except (TypeError, ValueError):
        # Older Pillow without multiline `anchor` support - fall back silently.
        draw.text((4, 4), label, fill=(120, 20, 20, 255))
    return image


def _fit_image(image: Image.Image, width: float, height: float, fit: str) -> Image.Image:
    w, h = max(1, round(width)), max(1, round(height))
    if fit == "contain":
        scale = min(w / image.width, h / image.height)
        nw, nh = max(1, round(image.width * scale)), max(1, round(image.height * scale))
        resized = image.resize((nw, nh), Image.LANCZOS)
        canvas = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        # Copy RGBA directly. Using the image as its own mask squares alpha,
        # weakening antialiased edges and fine lettering during downscaling.
        canvas.paste(resized, ((w - nw) // 2, (h - nh) // 2))
        return canvas
    if fit == "cover":
        scale = max(w / image.width, h / image.height)
        nw, nh = max(1, round(image.width * scale)), max(1, round(image.height * scale))
        resized = image.resize((nw, nh), Image.LANCZOS)
        left, top = (nw - w) // 2, (nh - h) // 2
        return resized.crop((left, top, left + w, top + h))
    # fit == "fill" (or anything unrecognized): stretch to exactly fit, same
    # as cr-renderer's own default `drawImageRect` behavior.
    return image.resize((w, h), Image.LANCZOS)
