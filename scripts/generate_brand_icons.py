"""Generate the Ruang favicon and installable-app icon set."""

from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
FAVICON_DIR = ROOT / "static" / "favicon"
SCALE = 4


def scaled_box(*coordinates: int) -> tuple[int, ...]:
    return tuple(coordinate * SCALE for coordinate in coordinates)


def build_icon() -> Image.Image:
    size = 160 * SCALE
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))

    start = (16, 117, 109)
    end = (16, 42, 43)
    gradient = Image.new("RGBA", (size, size))
    pixels = gradient.load()
    for y in range(size):
        for x in range(size):
            progress = (x + y) / (2 * (size - 1))
            pixels[x, y] = tuple(
                round(start[channel] * (1 - progress) + end[channel] * progress) for channel in range(3)
            ) + (255,)

    background_mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(background_mask).rounded_rectangle(
        scaled_box(8, 8, 152, 152),
        radius=42 * SCALE,
        fill=255,
    )
    image.alpha_composite(Image.composite(gradient, image, background_mask))

    draw = ImageDraw.Draw(image)
    cream = "#F6F4EC"
    mint = "#B7F7D8"
    teal = "#145A57"

    draw.rounded_rectangle(
        scaled_box(44, 30, 120, 144),
        radius=38 * SCALE,
        fill=cream,
    )
    draw.rectangle(scaled_box(44, 68, 120, 144), fill=cream)
    draw.rounded_rectangle(
        scaled_box(65, 50, 99, 145),
        radius=18 * SCALE,
        fill=teal,
    )
    draw.rectangle(scaled_box(65, 69, 99, 145), fill=teal)
    draw.rectangle(scaled_box(78, 88, 99, 126), fill=mint)

    spark = [
        (126, 31),
        (129, 40),
        (138, 43),
        (129, 46),
        (126, 55),
        (123, 46),
        (114, 43),
        (123, 40),
    ]
    draw.polygon(
        [(x * SCALE, y * SCALE) for x, y in spark],
        fill=mint,
    )

    return image.resize((512, 512), Image.Resampling.LANCZOS)


def main() -> None:
    FAVICON_DIR.mkdir(parents=True, exist_ok=True)
    icon = build_icon()

    outputs = {
        "web-app-manifest-512x512.png": 512,
        "web-app-manifest-192x192.png": 192,
        "apple-touch-icon.png": 180,
        "favicon-96x96.png": 96,
    }
    for filename, size in outputs.items():
        icon.resize((size, size), Image.Resampling.LANCZOS).save(
            FAVICON_DIR / filename,
            optimize=True,
        )

    icon.save(
        FAVICON_DIR / "favicon.ico",
        sizes=[(16, 16), (32, 32), (48, 48)],
    )


if __name__ == "__main__":
    main()
