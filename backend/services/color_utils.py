import colorsys
import re

def rgb_to_hex(rgb):
    match = re.match(r"rgba?\((\d+),\s*(\d+),\s*(\d+)", rgb)
    if not match:
        return None

    r, g, b = map(int, match.groups())
    return "#{:02x}{:02x}{:02x}".format(r, g, b)


def hsl_to_hex(hsl):
    match = re.match(r"hsla?\((\d+),\s*(\d+)%?,\s*(\d+)%?", hsl)
    if not match:
        return None

    h, s, l = map(int, match.groups())
    h = h / 360
    s = s / 100
    l = l / 100

    r, g, b = colorsys.hls_to_rgb(h, l, s)
    return "#{:02x}{:02x}{:02x}".format(
        int(r * 255), int(g * 255), int(b * 255)
    )


def normalize_hex(color):
    match = re.fullmatch(r"#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})", color.strip())
    if not match:
        return None

    value = match.group(1)
    if len(value) == 3:
        value = "".join(ch * 2 for ch in value)
    return f"#{value.lower()}"


def clean_colors(color_list):
    cleaned = set()

    for color in color_list:
        if not color:
            continue

        color = str(color).strip()

        # remove fully transparent rgba colors
        if color.lower().startswith("rgba"):
            alpha_match = re.search(r"rgba\([^\)]*,\s*([0-9]*\.?[0-9]+)\s*\)", color.lower())
            if alpha_match and float(alpha_match.group(1)) == 0:
                continue

        hex_color = normalize_hex(color)
        if hex_color:
            cleaned.add(hex_color)
            continue

        # handle HSL
        if color.lower().startswith("hsl"):
            hex_color = hsl_to_hex(color)
            if hex_color:
                cleaned.add(hex_color)
                continue

        hex_color = rgb_to_hex(color)
        if hex_color:
            cleaned.add(hex_color)

    return list(cleaned)


def _hex_to_rgb(hex_color):
    value = hex_color.lstrip("#")
    if len(value) != 6:
        return None
    return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))


def is_grey(rgb):
    r, g, b = rgb
    return abs(r - g) < 15 and abs(g - b) < 15


def is_colorful(rgb):
    r, g, b = rgb
    return (max(rgb) - min(rgb)) >= 40


def color_distance(c1, c2):
    rgb1 = _hex_to_rgb(c1)
    rgb2 = _hex_to_rgb(c2)
    if rgb1 is None or rgb2 is None:
        return 999

    r1, g1, b1 = rgb1
    r2, g2, b2 = rgb2
    return abs(r1 - r2) + abs(g1 - g2) + abs(b1 - b2)


def merge_similar_colors(colors, threshold=30):
    merged = []

    for color in colors:
        if not any(color_distance(color, c) < threshold for c in merged):
            merged.append(color)

    return merged


def classify_colors(hex_colors):
    tokens = {
        "background": [],
        "text": [],
        "accent": [],
    }

    for color in hex_colors:
        rgb = _hex_to_rgb(color)
        if rgb is None:
            continue

        r, g, b = rgb
        luminance = 0.2126 * r + 0.7152 * g + 0.0722 * b

        # LIGHT → background
        if luminance >= 210:
            tokens["background"].append(color)

        # DARK colors are often text, but saturated dark hues can be brand accents.
        elif luminance <= 80:
            if is_colorful(rgb):
                tokens["accent"].append(color)
            else:
                tokens["text"].append(color)

        else:
            # MID RANGE → check if colorful
            if not is_grey(rgb):
                tokens["accent"].append(color)
            else:
                tokens["text"].append(color)

    # Deduplicate
    for key in tokens:
        tokens[key] = list(dict.fromkeys(tokens[key]))

    tokens["background"] = merge_similar_colors(tokens["background"], threshold=45)[:2]
    tokens["text"] = merge_similar_colors(tokens["text"], threshold=40)[:4]
    tokens["accent"] = merge_similar_colors(tokens["accent"], threshold=30)[:2]

    return tokens