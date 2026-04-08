from fastapi import APIRouter, HTTPException
from datetime import datetime, timezone
import hashlib
from pydantic import BaseModel
from urllib.parse import urlparse

from services.color_utils import clean_colors, classify_colors, color_distance
from services.scraper import scrape_design
from services.theme_state import apply_locked_overrides, get_theme_state, save_theme_state

router = APIRouter()


class ThemeStatePayload(BaseModel):
    url: str
    locked_tokens: list[str] = []
    overrides: dict = {}


class TokenUpdatePayload(BaseModel):
    url: str
    category: str
    token: str
    value: str | int | float
    lock: bool = False


class TokenDeletePayload(BaseModel):
    url: str
    category: str
    token: str
    unlock: bool = True


def _hex_to_rgb(hex_color: str):
    value = hex_color.lstrip("#")
    if len(value) != 6:
        return None
    try:
        return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return None


def _avg_background_brightness(background_colors):
    rgbs = [_hex_to_rgb(color) for color in background_colors]
    rgbs = [rgb for rgb in rgbs if rgb is not None]
    if not rgbs:
        return 255

    brightness = [0.2126 * r + 0.7152 * g + 0.0722 * b for r, g, b in rgbs]
    return sum(brightness) / len(brightness)


def _rgb_to_hex(rgb):
    r, g, b = rgb
    return f"#{int(r):02x}{int(g):02x}{int(b):02x}"


def _darken_hex(hex_color, factor=0.86):
    rgb = _hex_to_rgb(hex_color) if hex_color else None
    if rgb is None:
        return "#d32f2f"
    r, g, b = rgb
    return _rgb_to_hex((max(0, round(r * factor)), max(0, round(g * factor)), max(0, round(b * factor))))


def _is_neutral(hex_color):
    rgb = _hex_to_rgb(hex_color) if hex_color else None
    if rgb is None:
        return False
    r, g, b = rgb
    return abs(r - g) <= 16 and abs(g - b) <= 16


def _interpolate_rgb(c1, c2, t):
    return (
        round(c1[0] + (c2[0] - c1[0]) * t),
        round(c1[1] + (c2[1] - c1[1]) * t),
        round(c1[2] + (c2[2] - c1[2]) * t),
    )


def build_neutral_scale(tokens):
    candidates = tokens.get("background", []) + tokens.get("text", [])
    neutral_candidates = [c for c in candidates if _is_neutral(c)]

    rgbs = [_hex_to_rgb(c) for c in neutral_candidates]
    rgbs = [rgb for rgb in rgbs if rgb is not None]

    if rgbs:
        mid = sorted(
            rgbs,
            key=lambda rgb: abs((0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]) - 127),
        )[0]
    else:
        mid = (119, 119, 119)

    white = (255, 255, 255)
    black = (0, 0, 0)

    return {
        "100": _rgb_to_hex(_interpolate_rgb(white, mid, 0.18)),
        "500": _rgb_to_hex(mid),
        "900": _rgb_to_hex(_interpolate_rgb(mid, black, 0.92)),
    }


def build_design_meta(tokens, typography, spacing):
    avg_brightness = _avg_background_brightness(tokens.get("background", []))
    color_mode = "light" if avg_brightness > 200 else "dark"

    base_spacing = spacing.get("base", 4)
    density = "comfortable"
    if base_spacing <= 3:
        density = "compact"
    elif base_spacing >= 8:
        density = "spacious"

    style = "modern"
    if len(tokens.get("accent", [])) <= 1 and len(typography.get("font_family", [])) <= 1:
        style = "modern-minimal"

    return {
        "style": style,
        "density": density,
        "color_mode": color_mode,
    }


def _token(value, source="extracted"):
    return {
        "value": value,
        "source": source,
    }


def _as_source_token_map(values, extracted_keys=None):
    extracted_keys = extracted_keys or set()
    return {
        key: _token(value, source="extracted" if key in extracted_keys else "computed")
        for key, value in values.items()
    }


def build_system_with_source(system_raw, extracted_color_pool=None):
    extracted_color_pool = extracted_color_pool or set()
    colors = system_raw.get("colors", {})
    typography = system_raw.get("typography", {})
    spacing = system_raw.get("spacing", {})
    radii = system_raw.get("radii", {})
    image_palette = system_raw.get("image_palette", {})
    components = system_raw.get("components", {})

    wrapped_colors = {}
    for key, value in colors.items():
        if key == "neutrals":
            continue
        source = "extracted" if value in extracted_color_pool else "computed"
        wrapped_colors[key] = _token(value, source=source)

    neutrals = colors.get("neutrals", {})
    wrapped_colors["neutrals"] = {
        key: _token(value, source="computed")
        for key, value in neutrals.items()
    }

    wrapped_typography = {
        "font_family": [_token(v, source="extracted") for v in typography.get("font_family", [])],
        "font_stack": _token(typography.get("font_stack"), source="computed") if typography.get("font_stack") else None,
        "primary_font": _token(typography.get("primary_font"), source="extracted") if typography.get("primary_font") else None,
        "body_size": _token(typography.get("body_size"), source="extracted") if typography.get("body_size") else None,
        "scale": [
            {
                "step": item.get("step"),
                "size": _token(item.get("size"), source=item.get("source", "extracted")),
                "weight": _token(item.get("weight"), source=item.get("source", "extracted")),
                "line_height": _token(item.get("line_height"), source=item.get("source", "extracted")),
                "letter_spacing": _token(item.get("letter_spacing"), source=item.get("source", "extracted")),
            }
            for item in typography.get("scale", [])
        ],
    }

    wrapped_spacing = _as_source_token_map(spacing, extracted_keys={"xs", "sm", "md", "lg"})
    wrapped_radii = _as_source_token_map(radii, extracted_keys={"sm", "md", "lg"})
    wrapped_image_palette = {
        "dominant": [_token(value, source="extracted") for value in image_palette.get("dominant", [])],
        "vibrant": _token(image_palette.get("vibrant"), source="extracted") if image_palette.get("vibrant") else None,
        "confidence": _token(round(float(image_palette.get("confidence", 0) or 0), 3), source="computed"),
        "sampled_images": _token(int(image_palette.get("sampled_images", 0) or 0), source="computed"),
    }

    return {
        "colors": wrapped_colors,
        "typography": wrapped_typography,
        "spacing": wrapped_spacing,
        "radii": wrapped_radii,
        "image_palette": wrapped_image_palette,
        "components": components,
    }


def _pick_darkest(colors):
    candidates = [(color, _luminance(color)) for color in colors if _luminance(color) is not None]
    if not candidates:
        return None
    return sorted(candidates, key=lambda x: x[1])[0][0]


def _pick_brightest(colors):
    candidates = [(color, _luminance(color)) for color in colors if _luminance(color) is not None]
    if not candidates:
        return None
    return sorted(candidates, key=lambda x: x[1], reverse=True)[0][0]


def build_semantic_colors(tokens, button_roles, image_palette=None, social_auth_colors=None):
    accents = tokens.get("accent", [])
    backgrounds = tokens.get("background", [])
    texts = tokens.get("text", [])
    image_palette = image_palette or {}
    social_auth_colors = social_auth_colors or []

    primary_button = (button_roles or {}).get("primary") if button_roles else None
    primary = (primary_button or {}).get("background") or (accents[0] if accents else _pick_darkest(texts))
    primary_foreground = (primary_button or {}).get("text")

    if primary_foreground is None:
        lum = _luminance(primary) if primary else None
        primary_foreground = "#ffffff" if lum is not None and lum < 140 else "#000000"

    surface = _pick_brightest(backgrounds) or "#ffffff"
    surface_alt = None
    if backgrounds:
        non_surface = [c for c in backgrounds if c != surface]
        surface_alt = non_surface[0] if non_surface else backgrounds[0]

    text_primary = _pick_darkest(texts) or "#000000"
    text_secondary = None
    if texts:
        non_primary_text = [c for c in texts if c != text_primary]
        text_secondary = non_primary_text[0] if non_primary_text else texts[0]

    social_pool = set(social_auth_colors)

    def _is_social_candidate(color):
        if color in social_pool:
            return True
        return any(color_distance(color, social) < 16 for social in social_pool)

    filtered_accents = [c for c in accents if c != primary and not _is_social_candidate(c)]

    brand = None
    vibrant = image_palette.get("vibrant")
    if vibrant and not _is_social_candidate(vibrant) and vibrant != primary:
        brand = vibrant
    elif filtered_accents:
        brand = filtered_accents[0]
    elif accents:
        non_primary_accent = [c for c in accents if c != primary]
        brand = non_primary_accent[0] if non_primary_accent else accents[0]

    return {
        "primary": primary,
        "primary_foreground": primary_foreground,
        "surface": surface,
        "surface_alt": surface_alt,
        "text_primary": text_primary,
        "text_secondary": text_secondary,
        "brand": brand,
        "neutrals": build_neutral_scale(tokens),
    }


def _normalize_to_hex(color_value):
    cleaned = clean_colors([color_value])
    return cleaned[0] if cleaned else None


def clean_button(btn):
    cleaned = {
        "background": _normalize_to_hex(btn.get("background")),
        "text": _normalize_to_hex(btn.get("text")),
        "border_color": _normalize_to_hex(btn.get("borderColor")),
        "border_width": btn.get("borderWidth"),
        "border_style": btn.get("borderStyle"),
        "padding": btn.get("padding"),
        "radius": btn.get("radius"),
        "font_size": btn.get("fontSize"),
        "font_weight": btn.get("fontWeight"),
        "count": btn.get("count", 0),
    }

    # Preserve explicit transparent backgrounds for ghost button detection/rendering.
    if cleaned["background"] is None and str(btn.get("background") or "").strip().lower() in {
        "transparent",
        "rgba(0,0,0,0)",
        "rgba(0, 0, 0, 0)",
    }:
        cleaned["background"] = "transparent"

    return cleaned


def _parse_px(value):
    if not value:
        return 0.0
    try:
        return float(str(value).replace("px", "").strip())
    except ValueError:
        return 0.0


def build_spacing_named_tokens(spacing):
    scale = spacing.get("scale", []) if spacing else []
    values = sorted({int(v) for v in scale if isinstance(v, (int, float)) and v > 0})

    if len(values) < 4:
        # Fallback to the current 4pt rhythm defaults.
        values = [4, 8, 16, 24]
    else:
        values = values[:4]

    base = values[0]
    return {
        "xs": values[0],
        "sm": values[1],
        "md": values[2],
        "lg": values[3],
        "xl": max(values[3] + base * 2, 32),
        "2xl": max(values[3] + base * 6, 48),
        "3xl": max(values[3] + base * 10, 64),
    }


def build_radii_tokens(buttons):
    radii = []
    for btn in buttons:
        radius = _parse_px(btn.get("radius"))
        if radius > 0:
            radii.append(int(round(radius)))

    if radii:
        # Most common extracted radius, clamped to a practical token range.
        dominant = max(set(radii), key=radii.count)
        lg = max(8, min(20, dominant))
    else:
        lg = 12

    return {
        "sm": "4px",
        "md": "8px",
        "lg": f"{lg}px",
        "pill": "9999px",
    }


def _luminance(hex_color):
    rgb = _hex_to_rgb(hex_color) if hex_color else None
    if not rgb:
        return None
    r, g, b = rgb
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _is_ghost_button(button):
    bg = button.get("background")
    border_width = _parse_px(button.get("border_width"))
    border_style = str(button.get("border_style") or "").lower()
    has_border = border_width > 0 and border_style not in {"none", "hidden", ""}
    return (bg is None or bg == "transparent") and has_border


def _is_primary_button(button, accent_colors):
    bg = button.get("background")
    if not bg:
        return False

    if bg in accent_colors:
        return True

    near_accent = any(color_distance(bg, accent) < 35 for accent in accent_colors)
    if near_accent:
        return True

    bg_lum = _luminance(bg)
    text_lum = _luminance(button.get("text"))
    if bg_lum is None or text_lum is None:
        return False

    high_contrast_cta = bg_lum < 70 and text_lum > 200
    return high_contrast_cta


def classify_buttons(buttons, tokens):
    ranked = sorted(buttons, key=lambda b: b.get("count", 0), reverse=True)
    accent_colors = tokens.get("accent", [])

    grouped = {
        "primary": None,
        "secondary": None,
        "ghost": None,
    }

    for btn in ranked:
        if _is_ghost_button(btn):
            if grouped["ghost"] is None:
                grouped["ghost"] = {
                    **btn,
                    "background": "transparent",
                }
            continue

        if _is_primary_button(btn, accent_colors):
            if grouped["primary"] is None:
                grouped["primary"] = btn
            continue

        if grouped["secondary"] is None:
            grouped["secondary"] = btn

    # Fallback: if no explicit primary found, promote dominant high-contrast solid button.
    if grouped["primary"] is None:
        fallback = next(
            (
                btn
                for btn in ranked
                if not _is_ghost_button(btn)
                and _luminance(btn.get("background")) is not None
                and _luminance(btn.get("text")) is not None
                and _luminance(btn.get("background")) < 90
                and _luminance(btn.get("text")) > 190
            ),
            None,
        )
        if fallback is not None:
            grouped["primary"] = fallback
            if grouped["secondary"] == fallback:
                grouped["secondary"] = None

    # Ensure we still provide a secondary when available.
    if grouped["secondary"] is None:
        grouped["secondary"] = next(
            (
                btn
                for btn in ranked
                if btn is not grouped["primary"] and not _is_ghost_button(btn)
            ),
            None,
        )

    for key in ("primary", "secondary", "ghost"):
        if grouped[key] is not None:
            grouped[key] = {**grouped[key], "source": grouped[key].get("source", "extracted")}

    return grouped


def _hex_red_score(hex_color):
    rgb = _hex_to_rgb(hex_color) if hex_color else None
    if not rgb:
        return -999
    r, g, b = rgb
    return r - (g + b) / 2


def _derive_error_color(tokens, semantic_colors, error_colors=None):
    text_candidates = tokens.get("text", [])
    accent_candidates = tokens.get("accent", [])
    all_candidates = (error_colors or []) + text_candidates + accent_candidates

    brand = semantic_colors.get("brand")
    primary = semantic_colors.get("primary")

    if all_candidates:
        scored = sorted(all_candidates, key=_hex_red_score, reverse=True)
        for candidate in scored:
            if _hex_red_score(candidate) <= 20:
                break
            if candidate == brand or candidate == primary:
                continue
            if brand and color_distance(candidate, brand) < 18:
                continue
            return candidate, "extracted"

    fallback = _darken_hex(brand, factor=0.86) if brand else "#d32f2f"
    if brand and color_distance(fallback, brand) < 18:
        fallback = "#d32f2f"
    if primary and color_distance(fallback, primary) < 18:
        fallback = "#b71c1c"
    if fallback == brand:
        fallback = "#d32f2f"
    return fallback, "computed"


def build_input_component(tokens, semantic_colors, spacing_tokens):
    v_pad = int(spacing_tokens.get("sm", 8))
    h_pad = int((spacing_tokens.get("sm", 8) + spacing_tokens.get("md", 16)) / 2)
    default_border = semantic_colors.get("neutrals", {}).get("100") or semantic_colors.get("surface_alt") or "#e0e0e0"

    error_color, error_source = _derive_error_color(tokens, semantic_colors)

    return {
        "default": {
            "background": semantic_colors.get("surface") or "#ffffff",
            "border_color": default_border,
            "padding": f"{v_pad}px {h_pad}px",
            "text": semantic_colors.get("text_primary") or "#111111",
            "placeholder": semantic_colors.get("text_secondary") or semantic_colors.get("neutrals", {}).get("500") or "#6b7280",
            "source": "extracted",
        },
        "focus": {
            "border_color": semantic_colors.get("primary") or "#000000",
            "source": "extracted",
        },
        "error": {
            "border_color": error_color,
            "source": error_source,
        },
    }


def build_card_component(tokens, semantic_colors, spacing_tokens, radii_tokens):
    padding = int(spacing_tokens.get("lg", 24))
    surface = semantic_colors.get("surface") or "#ffffff"
    bg_candidate = semantic_colors.get("surface_alt") or semantic_colors.get("neutrals", {}).get("100")
    neutral_values = set((semantic_colors.get("neutrals") or {}).values())
    if not bg_candidate or bg_candidate in neutral_values:
        bg_candidate = surface

    border_candidate = semantic_colors.get("neutrals", {}).get("500") or "#d1d5db"
    text_group = set(tokens.get("text", []))
    if semantic_colors.get("text_primary"):
        text_group.add(semantic_colors.get("text_primary"))
    if semantic_colors.get("text_secondary"):
        text_group.add(semantic_colors.get("text_secondary"))
    if border_candidate in text_group:
        border_candidate = semantic_colors.get("neutrals", {}).get("100") or "#e7e7e7"

    return {
        "background": bg_candidate,
        "border_color": border_candidate,
        "border_width": "1px",
        "radius": radii_tokens.get("lg", "12px"),
        "padding": f"{padding}px",
        "shadow": "0 1px 3px rgba(0,0,0,0.08)",
        "source": "computed",
    }


def ensure_secondary_button(button_roles, semantic_colors, spacing_tokens, radii_tokens, typography):
    primary = button_roles.get("primary")
    secondary = button_roles.get("secondary")

    should_compute = secondary is None
    if primary and secondary and primary.get("background") == secondary.get("background"):
        should_compute = True

    if should_compute:
        text_color = semantic_colors.get("text_primary") or "#051316"
        body_size = typography.get("body_size") or "14px"
        button_roles["secondary"] = {
            "background": "transparent",
            "text": text_color,
            "border_color": text_color,
            "border_width": "1px",
            "border_style": "solid",
            "padding": f"{spacing_tokens.get('sm', 8)}px {spacing_tokens.get('lg', 24)}px",
            "radius": radii_tokens.get("lg", "12px"),
            "font_size": body_size,
            "font_weight": "500",
            "source": "computed",
        }

    return button_roles


def ensure_caption_step(typography):
    scale = typography.get("scale", [])
    body_size = _parse_px(typography.get("body_size"))
    if body_size <= 0:
        body_size = 14

    target_caption = max(11, int(round(body_size)) - 2)
    caption_idx = next((i for i, step in enumerate(scale) if step.get("step") == "caption"), None)

    if caption_idx is not None:
        current = scale[caption_idx]
        caption_size = _parse_px(current.get("size"))
        if caption_size <= 0 or caption_size >= body_size:
            scale[caption_idx] = {
                **current,
                "size": f"{target_caption}px",
                "source": "computed",
            }
    else:
        scale.append(
            {
                "step": "caption",
                "size": f"{target_caption}px",
                "weight": 400,
                "line_height": 1.4,
                "letter_spacing": "0.01em",
                "source": "computed",
            }
        )

    typography["scale"] = scale
    return typography


def build_site_id(url):
    parsed = urlparse(url)
    host = parsed.netloc.lower().replace("www.", "")
    return host.replace(".", "_")


def _clamp(value, min_value=0, max_value=255):
    return max(min_value, min(max_value, int(value)))


def _hex_from_rgb(r, g, b):
    return f"#{_clamp(r):02x}{_clamp(g):02x}{_clamp(b):02x}"


def _adjust_color(hex_color, delta):
    rgb = _hex_to_rgb(hex_color)
    if rgb is None:
        return hex_color
    r, g, b = rgb
    return _hex_from_rgb(r + delta, g + delta, b + delta)


def _simulate_design_data(url):
    site_id = build_site_id(url)
    digest = hashlib.sha256(site_id.encode("utf-8")).hexdigest()

    r = int(digest[0:2], 16)
    g = int(digest[2:4], 16)
    b = int(digest[4:6], 16)

    primary = _hex_from_rgb(max(20, r // 2), max(20, g // 2), max(20, b // 2))
    brand = _hex_from_rgb(r, g, b)
    surface = "#f7f7f7"
    text = "#111111"

    return {
        "colors": [surface, "#ffffff", text, primary, brand, _adjust_color(brand, -28)],
        "typography": {
            "font_family": ["Inter"],
            "primary_font": "Inter",
            "body_size": "14px",
            "scale": [
                {"step": "display", "size": "56px", "weight": 700, "line_height": 1.05, "letter_spacing": "-0.02em", "source": "computed"},
                {"step": "h1", "size": "40px", "weight": 700, "line_height": 1.1, "letter_spacing": "-0.015em", "source": "computed"},
                {"step": "h2", "size": "30px", "weight": 600, "line_height": 1.2, "letter_spacing": "-0.01em", "source": "computed"},
                {"step": "body", "size": "14px", "weight": 400, "line_height": 1.5, "letter_spacing": "0em", "source": "computed"},
            ],
        },
        "spacing": {"base": 4, "scale": [4, 8, 16, 24, 32]},
        "buttons": [
            {
                "background": primary,
                "text": "#ffffff",
                "borderColor": primary,
                "borderWidth": "1px",
                "borderStyle": "solid",
                "padding": "8px 24px",
                "radius": "12px",
                "fontSize": "14px",
                "fontWeight": "600",
                "count": 2,
            }
        ],
        "image_palette": {
            "dominant": [brand, _adjust_color(brand, 16), _adjust_color(brand, -16), "#f0f0f0", "#d9d9d9"],
            "vibrant": brand,
            "confidence": 0.35,
            "sampled_images": 0,
        },
        "social_auth_colors": [],
        "error_colors": [_adjust_color(brand, -30)],
    }


def _get_state_defaults(url):
    site_id = build_site_id(url)
    state = get_theme_state(site_id)
    if state is None:
        state = {
            "site_id": site_id,
            "version": 0,
            "locked_tokens": [],
            "overrides": {},
            "history": [],
            "url": url,
        }
    return state


def _token_lock_key(category, token):
    category_map = {
        "colors": "color",
        "typography": "typography",
        "spacing": "spacing",
    }
    prefix = category_map.get(category)
    if prefix is None:
        raise HTTPException(status_code=400, detail="Invalid category. Use colors, typography, or spacing.")
    return f"{prefix}.{token}"


@router.post("/scrape")
async def scrape(url: str):
    try:
        site_id = build_site_id(url)
        existing_state = get_theme_state(site_id)
        if existing_state is None:
            existing_state = save_theme_state(
                site_id=site_id,
                url=url,
                locked_tokens=[],
                overrides={},
            )

        scrape_mode = "live"
        scrape_issue = None
        try:
            design_data = await scrape_design(url)
        except Exception as scrape_exc:
            # Graceful fallback for bot-protected/paywalled/blocked targets.
            scrape_mode = "simulated"
            scrape_issue = str(scrape_exc)
            design_data = _simulate_design_data(url)
        raw_colors = design_data.get("colors", [])
        typography = design_data.get("typography", {})
        spacing = design_data.get("spacing", {})
        buttons = design_data.get("buttons", [])
        image_palette_raw = design_data.get("image_palette", {})
        image_palette_source = design_data.get("image_palette_source") or image_palette_raw.get("source")
        image_palette_confidence = design_data.get("image_palette_confidence", image_palette_raw.get("confidence", 0))
        image_palette_sampled_images = design_data.get("image_palette_sampled_images", image_palette_raw.get("sampled_images", 0))
        social_auth_colors_raw = design_data.get("social_auth_colors", [])
        error_colors_raw = design_data.get("error_colors", [])
        print("RAW COLORS:", raw_colors[:20])
        clean = clean_colors(raw_colors[:30])
        structured = classify_colors(clean)
        typography = ensure_caption_step(typography)
        typography["font_stack"] = f'"{typography.get("primary_font") or "System"}", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif'
        meta = build_design_meta(structured, typography, spacing)
        clean_buttons = [clean_button(b) for b in buttons]
        button_roles = classify_buttons(clean_buttons, structured)
        image_vibrant_list = clean_colors([image_palette_raw.get("vibrant")])
        image_vibrant = image_vibrant_list[0] if image_vibrant_list else None
        social_auth_colors = clean_colors(social_auth_colors_raw)
        semantic_colors = build_semantic_colors(
            structured,
            button_roles,
            image_palette={"vibrant": image_vibrant},
            social_auth_colors=social_auth_colors,
        )
        # Prefer image-derived brand when available and non-social.
        if image_vibrant and not any(color_distance(image_vibrant, c) < 16 for c in social_auth_colors):
            semantic_colors["brand"] = image_vibrant

        error_colors = clean_colors(error_colors_raw)
        danger_color, _danger_source = _derive_error_color(structured, semantic_colors, error_colors=error_colors)
        semantic_colors["danger"] = danger_color
        if semantic_colors.get("danger") == semantic_colors.get("brand"):
            semantic_colors["danger"] = "#d32f2f"
        spacing_tokens = build_spacing_named_tokens(spacing)
        radii_tokens = build_radii_tokens(clean_buttons)
        button_roles = ensure_secondary_button(button_roles, semantic_colors, spacing_tokens, radii_tokens, typography)
        input_component = build_input_component(structured, semantic_colors, spacing_tokens)
        card_component = build_card_component(structured, semantic_colors, spacing_tokens, radii_tokens)
        image_dominant = clean_colors(image_palette_raw.get("dominant", []))[:5]
        image_vibrant = image_vibrant or (semantic_colors.get("brand") or semantic_colors.get("primary"))
        image_palette_confidence = float(image_palette_confidence or 0)
        if image_palette_confidence <= 0 and image_dominant:
            # If upstream confidence was lost but palette exists, keep a non-zero reliability baseline.
            if str(image_palette_source or "").startswith("screenshot"):
                image_palette_confidence = 0.42
            else:
                image_palette_confidence = 0.28
        image_palette_sampled_images = int(image_palette_sampled_images or 0)
        image_palette = {
            "dominant": image_dominant,
            "vibrant": image_vibrant,
            "confidence": image_palette_confidence,
            "sampled_images": image_palette_sampled_images,
        }
        system_raw = {
            "colors": semantic_colors,
            "typography": typography,
            "spacing": spacing_tokens,
            "radii": radii_tokens,
            "image_palette": image_palette,
            "components": {
                "buttons": button_roles,
                "input": input_component,
                "card": card_component,
            },
        }
        extracted_color_pool = set(structured.get("background", []) + structured.get("text", []) + structured.get("accent", []))
        system = build_system_with_source(system_raw, extracted_color_pool=extracted_color_pool)

        extracted_at = datetime.now(timezone.utc).isoformat()
        system = apply_locked_overrides(system, existing_state)

        current_version = (existing_state or {}).get("version", 0)
        current_locked_tokens = (existing_state or {}).get("locked_tokens", [])
        meta = {
            **meta,
            "version": current_version,
            "extracted_at": extracted_at,
            "locked_tokens": current_locked_tokens,
            "site_id": site_id,
            "scrape_mode": scrape_mode,
            "scrape_issue": scrape_issue,
            "image_palette_source": image_palette_source,
            "image_palette_confidence": round(float(image_palette_confidence or 0), 3),
            "image_palette_sampled_images": int(image_palette_sampled_images or 0),
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Scrape failed: {exc}") from exc

    return {
        "url": url,
        "system": system,
        "meta": meta,
        "state": {
            "version": current_version,
            "locked_tokens": current_locked_tokens,
            "overrides": (existing_state or {}).get("overrides", {}),
            "history": (existing_state or {}).get("history", []),
        },
    }


@router.get("/theme-state")
async def get_theme_state_by_url(url: str):
    site_id = build_site_id(url)
    state = get_theme_state(site_id)
    if state is None:
        return {
            "site_id": site_id,
            "version": 0,
            "locked_tokens": [],
            "overrides": {},
            "history": [],
        }
    return state


@router.post("/theme-state")
async def persist_theme_state(payload: ThemeStatePayload):
    site_id = build_site_id(payload.url)
    state = save_theme_state(
        site_id=site_id,
        url=payload.url,
        locked_tokens=payload.locked_tokens,
        overrides=payload.overrides,
    )
    return state


@router.get("/tokens")
async def get_tokens(url: str):
    state = _get_state_defaults(url)
    return {
        "site_id": state.get("site_id"),
        "version": state.get("version", 0),
        "locked_tokens": state.get("locked_tokens", []),
        "overrides": state.get("overrides", {}),
    }


@router.put("/tokens")
async def update_token(payload: TokenUpdatePayload):
    state = _get_state_defaults(payload.url)
    overrides = state.get("overrides", {}) if isinstance(state.get("overrides"), dict) else {}
    category_bucket = overrides.get(payload.category, {}) if isinstance(overrides.get(payload.category), dict) else {}
    category_bucket[payload.token] = payload.value
    overrides[payload.category] = category_bucket

    lock_key = _token_lock_key(payload.category, payload.token)
    locked_tokens = set(state.get("locked_tokens", []))
    if payload.lock:
        locked_tokens.add(lock_key)

    saved = save_theme_state(
        site_id=state["site_id"],
        url=payload.url,
        locked_tokens=sorted(locked_tokens),
        overrides=overrides,
    )
    return saved


@router.delete("/tokens")
async def delete_token(payload: TokenDeletePayload):
    state = _get_state_defaults(payload.url)
    overrides = state.get("overrides", {}) if isinstance(state.get("overrides"), dict) else {}
    category_bucket = overrides.get(payload.category, {}) if isinstance(overrides.get(payload.category), dict) else {}
    category_bucket.pop(payload.token, None)
    overrides[payload.category] = category_bucket

    lock_key = _token_lock_key(payload.category, payload.token)
    locked_tokens = set(state.get("locked_tokens", []))
    if payload.unlock:
        locked_tokens.discard(lock_key)

    saved = save_theme_state(
        site_id=state["site_id"],
        url=payload.url,
        locked_tokens=sorted(locked_tokens),
        overrides=overrides,
    )
    return saved

