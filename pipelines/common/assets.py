"""Read-only metadata for packaged artwork; never modify or replace pixels."""

from functools import lru_cache
from pathlib import Path

from PIL import Image

ASSETS_DIR = Path(__file__).resolve().parents[2] / "brand_kit" / "assets"


@lru_cache(maxsize=128)
def asset_info(asset_id: str) -> dict:
    path = ASSETS_DIR / asset_id
    if not path.is_file():
        return {"available": False}
    with Image.open(path) as image:
        return {"available": True, "width": image.width, "height": image.height,
                "visible_bounds": image.convert("RGBA").getchannel("A").getbbox()}


def unavailable_unit(source: dict, unit: dict) -> bool:
    return all(source["elements"][i]["type"] == "image"
               and not asset_info(source["elements"][i]["asset_id"])["available"]
               for i in unit["idx"])
