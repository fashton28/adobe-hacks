from PIL import Image, ImageDraw

from .colorutil import parse_rgba


def render_shape(element: dict) -> Image.Image:
    """Rasterize a `shape` element to an RGBA PIL image.

    Crello's schema has no notion of vector shapes (only text/image
    elements), so shapes are pre-rendered to a PNG here and handed to
    cr-renderer as a regular image element. The element's own `opacity` is
    NOT baked in here - cr-renderer applies that separately as paint alpha
    when it composites the image, so baking it in too would double it up.
    """
    width = max(1, round(element.get("width", 1)))
    height = max(1, round(element.get("height", 1)))
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    r, g, b, _alpha = parse_rgba(element.get("fill_color"), default=(200, 200, 200, 1.0))
    fill = (r, g, b, 255)

    shape_type = element.get("shape_type", "rectangle")
    if shape_type == "ellipse":
        draw.ellipse([0, 0, width - 1, height - 1], fill=fill)
    elif shape_type == "line":
        stroke_r, stroke_g, stroke_b, _sa = parse_rgba(
            element.get("stroke_color") or element.get("fill_color"), default=(0, 0, 0, 1.0)
        )
        stroke_width = max(1, round(element.get("stroke_width", 1) or 1))
        draw.line([0, height // 2, width - 1, height // 2], fill=(stroke_r, stroke_g, stroke_b, 255), width=stroke_width)
    else:
        radius = max(0, min(element.get("corner_radius", 0), width / 2, height / 2))
        if radius > 0:
            draw.rounded_rectangle([0, 0, width - 1, height - 1], radius=radius, fill=fill)
        else:
            draw.rectangle([0, 0, width - 1, height - 1], fill=fill)

    return image


def shape_fill_alpha(element: dict) -> float:
    """Return the alpha channel embedded in `fill_color`, e.g. `rgba(1,2,3,0.5)`."""
    _r, _g, _b, alpha = parse_rgba(element.get("fill_color"), default=(0, 0, 0, 1.0))
    return alpha
