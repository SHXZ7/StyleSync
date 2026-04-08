from collections import Counter
from io import BytesIO

try:
    from PIL import Image
except Exception:  # pragma: no cover - optional dependency
    Image = None

try:
  from colorthief import ColorThief
except Exception:  # pragma: no cover - optional dependency
  ColorThief = None


def extract_image_palette_from_dom(page):
    """Extract dominant/vibrant colors from in-page images via canvas sampling."""
    return page.evaluate(
        """
        async () => {
          const viewportH = window.innerHeight || 900;
          const imageNodes = Array.from(document.querySelectorAll("img"))
            .filter((img) => img && img.naturalWidth > 0 && img.naturalHeight > 0)
            .slice(0, 36);

          const dominantMap = new Map();
          const vibrantMap = new Map();
          let totalWeight = 0;

          const addColor = (r, g, b, weight = 1) => {
            const q = (v) => Math.max(0, Math.min(255, Math.round(v / 16) * 16));
            const qr = q(r);
            const qg = q(g);
            const qb = q(b);
            const key = `rgb(${qr}, ${qg}, ${qb})`;

            dominantMap.set(key, (dominantMap.get(key) || 0) + weight);
            totalWeight += weight;

            const maxC = Math.max(qr, qg, qb);
            const minC = Math.min(qr, qg, qb);
            const sat = maxC === 0 ? 0 : (maxC - minC) / maxC;
            const score = sat * 100 + (dominantMap.get(key) || 0) * 0.06;
            vibrantMap.set(key, Math.max(vibrantMap.get(key) || 0, score));
          };

          const sampleImage = (img) => {
            const canvas = document.createElement("canvas");
            const ctx = canvas.getContext("2d", { willReadFrequently: true });
            if (!ctx) return;

            const w = 24;
            const h = 24;
            canvas.width = w;
            canvas.height = h;

            const rect = img.getBoundingClientRect();
            const area = Math.max(0, rect.width * rect.height);
            const isAboveFold = rect.top >= -40 && rect.top <= viewportH * 0.9;
            const isLikelyHero = area > 50000;
            const areaWeight = Math.min(3, Math.max(0.6, area / 25000));
            const positionWeight = isAboveFold ? 1.35 : 0.8;
            const heroWeight = isLikelyHero ? 1.25 : 1;
            const imageWeight = areaWeight * positionWeight * heroWeight;

            try {
              ctx.drawImage(img, 0, 0, w, h);
              const data = ctx.getImageData(0, 0, w, h).data;
              for (let i = 0; i < data.length; i += 16) {
                const r = data[i];
                const g = data[i + 1];
                const b = data[i + 2];
                const a = data[i + 3];

                if (a < 180) continue;
                const maxC = Math.max(r, g, b);
                const minC = Math.min(r, g, b);
                if (maxC > 248 && minC > 238) continue;
                if (maxC < 18 && minC < 12) continue;
                if (maxC - minC < 8 && maxC > 220) continue;

                addColor(r, g, b, imageWeight);
              }
            } catch {
              // Cross-origin image canvas taint or draw errors.
            }
          };

          imageNodes.forEach(sampleImage);

          const dominantEntries = Array.from(dominantMap.entries())
            .sort((a, b) => b[1] - a[1])
            .slice(0, 8);

          const dominant = dominantEntries
            .filter(([, score]) => score >= (dominantEntries[0]?.[1] || 0) * 0.18)
            .slice(0, 5)
            .map(([color]) => color);

          const vibrant = Array.from(vibrantMap.entries())
            .sort((a, b) => b[1] - a[1])[0]?.[0] || null;

          const dominantLead = dominantEntries[0]?.[1] || 0;
          const confidence = totalWeight > 0
            ? Math.max(0.15, Math.min(0.98, dominantLead / totalWeight + (dominant.length >= 3 ? 0.08 : 0)))
            : 0.2;

          return {
            dominant,
            vibrant,
            source: "dom-images",
            confidence,
            sampled_images: imageNodes.length,
          };
        }
        """
    )


def _rgb_to_hex(r, g, b):
    return f"#{int(r):02x}{int(g):02x}{int(b):02x}"


def _is_low_info_rgb(r, g, b):
  max_c = max(r, g, b)
  min_c = min(r, g, b)
  if max_c > 245 and min_c > 238:
    return True
  if max_c < 20 and min_c < 14:
    return True
  if (max_c - min_c) < 7 and max_c > 228:
    return True
  return False


def _score_confidence(counts, dominant_count):
  total = sum(counts.values())
  if total <= 0:
    return 0.1
  dominance_ratio = dominant_count / total
  diversity = len(counts)
  diversity_bonus = min(0.18, diversity * 0.015)
  return max(0.18, min(0.94, dominance_ratio + diversity_bonus))


def _rgb_luminance(rgb):
  r, g, b = rgb
  return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255


def _rgb_saturation(rgb):
  r, g, b = rgb
  max_c = max(r, g, b)
  min_c = min(r, g, b)
  return 0 if max_c == 0 else (max_c - min_c) / max_c


def _is_neutral_rgb(rgb):
  r, g, b = rgb
  return abs(r - g) <= 14 and abs(g - b) <= 14 and abs(r - b) <= 14


def _pick_vibrant_rgb(counts):
  total = sum(counts.values()) or 1

  scored = []
  for rgb, count in counts.most_common(24):
    sat = _rgb_saturation(rgb)
    lum = _rgb_luminance(rgb)
    weight = count / total
    # Prefer saturated, visible colors while still respecting frequency.
    score = sat * 1.55 + lum * 0.25 + weight * 0.2
    if _is_neutral_rgb(rgb):
      score -= 0.15
    if lum < 0.12:
      score -= 0.2
    scored.append((score, rgb))

  if not scored:
    return None

  scored.sort(key=lambda x: x[0], reverse=True)
  return scored[0][1]


def _palette_from_image_bytes(image_bytes, source, sampled_images=0):
  if Image is None:
    return {
      "dominant": [],
      "vibrant": None,
      "source": f"{source}-no-pil",
      "confidence": 0.08,
      "sampled_images": sampled_images,
    }

  image = Image.open(BytesIO(image_bytes)).convert("RGB")
  image.thumbnail((180, 180))
  pixels = list(image.getdata())

  quantized = [
    (
      int(round(r / 16) * 16),
      int(round(g / 16) * 16),
      int(round(b / 16) * 16),
    )
    for r, g, b in pixels
    if not _is_low_info_rgb(r, g, b)
  ]

  if not quantized:
    return {
      "dominant": [],
      "vibrant": None,
      "source": f"{source}-filtered",
      "confidence": 0.12,
      "sampled_images": sampled_images,
    }

  counts = Counter(quantized)
  dominant_count = counts.most_common(1)[0][1]
  ranked = counts.most_common(32)
  accent_candidates = [
    rgb
    for rgb, _ in ranked
    if _rgb_saturation(rgb) >= 0.22 and 0.14 <= _rgb_luminance(rgb) <= 0.9
  ]

  dominant_rgb = []
  for rgb, count in ranked:
    if count < dominant_count * 0.16:
      continue
    if _is_neutral_rgb(rgb) and _rgb_luminance(rgb) < 0.22:
      continue
    dominant_rgb.append(rgb)
    if len(dominant_rgb) >= 5:
      break

  if not dominant_rgb:
    dominant_rgb = [rgb for rgb, _ in counts.most_common(5)]

  if accent_candidates and not any(_rgb_saturation(rgb) >= 0.2 for rgb in dominant_rgb):
    dominant_rgb = [*dominant_rgb[:4], accent_candidates[0]]

  vibrant_rgb = _pick_vibrant_rgb(counts) or (dominant_rgb[0] if dominant_rgb else counts.most_common(1)[0][0])
  dominant_hex = [_rgb_to_hex(*rgb) for rgb in dominant_rgb]

  if ColorThief is not None:
    try:
      thief = ColorThief(BytesIO(image_bytes))
      ct_palette = thief.get_palette(color_count=5, quality=6) or []
      ct_dominant = thief.get_color(quality=5)
      merged = []
      for rgb in [ct_dominant, *ct_palette, *dominant_rgb]:
        if not rgb:
          continue
        hex_value = _rgb_to_hex(*rgb)
        if hex_value not in merged:
          merged.append(hex_value)
      if merged:
        accent_ct = [rgb for rgb in ct_palette if _rgb_saturation(rgb) >= 0.2 and 0.14 <= _rgb_luminance(rgb) <= 0.9]
        if accent_ct:
          accent_hex = _rgb_to_hex(*accent_ct[0])
          if accent_hex not in merged:
            merged.append(accent_hex)
        dominant_hex = merged[:5]
        vibrant_rgb = accent_ct[0] if accent_ct else (ct_dominant or vibrant_rgb)
    except Exception:
      pass

  confidence = _score_confidence(counts, dominant_count)
  return {
    "dominant": dominant_hex,
    "vibrant": _rgb_to_hex(*vibrant_rgb) if vibrant_rgb else (dominant_hex[0] if dominant_hex else None),
    "source": source,
    "confidence": confidence,
    "sampled_images": sampled_images,
  }


def extract_image_palette_from_targets(page):
  """Prefer logo/hero image crops for cleaner brand palettes."""
  try:
    handles = page.query_selector_all("img")[:40]
    candidates = []
    for handle in handles:
      try:
        meta = handle.evaluate(
          """
          (img) => {
            if (!img || !img.naturalWidth || !img.naturalHeight) return null;
            const rect = img.getBoundingClientRect();
            const attrs = [img.alt || "", img.className || "", img.id || "", img.src || ""].join(" ").toLowerCase();
            const area = Math.max(0, rect.width * rect.height);
            const isHero = /hero|banner|cover/.test(attrs);
            const isLogo = /logo|brand|mark/.test(attrs);
            const foldBoost = rect.top < window.innerHeight ? 1.15 : 0.85;
            const score = Math.min(4, Math.max(0.5, area / 24000)) * foldBoost * (isHero ? 1.3 : 1) * (isLogo ? 1.25 : 1);
            return { score };
          }
          """
        )
        if not meta:
          continue
        candidates.append((meta.get("score", 0), handle))
      except Exception:
        continue

    if not candidates:
      return {
        "dominant": [],
        "vibrant": None,
        "source": "dom-targets-empty",
        "confidence": 0.12,
        "sampled_images": 0,
      }

    candidates.sort(key=lambda x: x[0], reverse=True)
    top = candidates[:3]

    palettes = []
    sampled = 0
    for _, handle in top:
      try:
        image_bytes = handle.screenshot(type="png")
        sampled += 1
        palettes.append(_palette_from_image_bytes(image_bytes, source="dom-targets", sampled_images=1))
      except Exception:
        continue

    if not palettes:
      return {
        "dominant": [],
        "vibrant": None,
        "source": "dom-targets-failed",
        "confidence": 0.12,
        "sampled_images": 0,
      }

    merged = []
    for p in palettes:
      for color in p.get("dominant", []):
        if color not in merged:
          merged.append(color)

    best = sorted(palettes, key=lambda p: p.get("confidence", 0), reverse=True)[0]
    return {
      "dominant": merged[:5],
      "vibrant": best.get("vibrant"),
      "source": "dom-targets",
      "confidence": min(0.96, max(0.2, sum(p.get("confidence", 0) for p in palettes) / len(palettes) + 0.06)),
      "sampled_images": sampled,
    }
  except Exception:
    return {
      "dominant": [],
      "vibrant": None,
      "source": "dom-targets-error",
      "confidence": 0.1,
      "sampled_images": 0,
    }


def extract_image_palette_from_screenshot(page):
    """Fallback palette extraction from page screenshot if DOM image sampling fails."""
    try:
        screenshot = page.screenshot(full_page=False)
        return _palette_from_image_bytes(screenshot, source="screenshot", sampled_images=0)
    except Exception:
        return {
            "dominant": [],
            "vibrant": None,
            "source": "screenshot-error",
            "confidence": 0.1,
            "sampled_images": 0,
        }


def extract_image_palette(page):
    dom_palette = extract_image_palette_from_dom(page)
    target_palette = extract_image_palette_from_targets(page)

    if (target_palette or {}).get("dominant"):
        target_conf = float((target_palette or {}).get("confidence", 0))
        dom_conf = float((dom_palette or {}).get("confidence", 0))
        if not (dom_palette or {}).get("dominant") or target_conf >= dom_conf + 0.05:
            return target_palette

    if (dom_palette or {}).get("dominant"):
        return dom_palette

    return extract_image_palette_from_screenshot(page)
