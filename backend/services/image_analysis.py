from collections import Counter
from io import BytesIO

try:
    from PIL import Image
except Exception:  # pragma: no cover - optional dependency
    Image = None


def extract_image_palette_from_dom(page):
    """Extract dominant/vibrant colors from in-page images via canvas sampling."""
    return page.evaluate(
        """
        async () => {
          const imageNodes = Array.from(document.querySelectorAll("img"))
            .filter((img) => img && img.naturalWidth > 0 && img.naturalHeight > 0)
            .slice(0, 24);

          const dominantMap = new Map();
          const vibrantMap = new Map();

          const addColor = (r, g, b) => {
            const q = (v) => Math.max(0, Math.min(255, Math.round(v / 16) * 16));
            const qr = q(r);
            const qg = q(g);
            const qb = q(b);
            const key = `rgb(${qr}, ${qg}, ${qb})`;

            dominantMap.set(key, (dominantMap.get(key) || 0) + 1);

            const maxC = Math.max(qr, qg, qb);
            const minC = Math.min(qr, qg, qb);
            const sat = maxC === 0 ? 0 : (maxC - minC) / maxC;
            const score = sat * 100 + (dominantMap.get(key) || 0) * 0.05;
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

                addColor(r, g, b);
              }
            } catch {
              // Cross-origin image canvas taint or draw errors.
            }
          };

          imageNodes.forEach(sampleImage);

          const dominant = Array.from(dominantMap.entries())
            .sort((a, b) => b[1] - a[1])
            .slice(0, 5)
            .map(([color]) => color);

          const vibrant = Array.from(vibrantMap.entries())
            .sort((a, b) => b[1] - a[1])[0]?.[0] || null;

          return {
            dominant,
            vibrant,
            source: "dom-images",
          };
        }
        """
    )


def _rgb_to_hex(r, g, b):
    return f"#{int(r):02x}{int(g):02x}{int(b):02x}"


def extract_image_palette_from_screenshot(page):
    """Fallback palette extraction from page screenshot if DOM image sampling fails."""
    if Image is None:
        return {
            "dominant": [],
            "vibrant": None,
            "source": "screenshot-no-pil",
        }

    try:
        screenshot = page.screenshot(full_page=False)
        image = Image.open(BytesIO(screenshot)).convert("RGB")
        image.thumbnail((120, 120))

        pixels = list(image.getdata())
        if not pixels:
            return {
                "dominant": [],
                "vibrant": None,
                "source": "screenshot-empty",
            }

        quantized = [
            (
                int(round(r / 16) * 16),
                int(round(g / 16) * 16),
                int(round(b / 16) * 16),
            )
            for r, g, b in pixels
            if not (r > 245 and g > 245 and b > 245)
        ]

        if not quantized:
            return {
                "dominant": [],
                "vibrant": None,
                "source": "screenshot-filtered",
            }

        counts = Counter(quantized)
        dominant_rgb = [rgb for rgb, _ in counts.most_common(5)]
        dominant_hex = [_rgb_to_hex(*rgb) for rgb in dominant_rgb]

        def saturation(rgb):
            r, g, b = rgb
            max_c = max(r, g, b)
            min_c = min(r, g, b)
            return 0 if max_c == 0 else (max_c - min_c) / max_c

        vibrant_rgb = sorted(dominant_rgb, key=saturation, reverse=True)[0] if dominant_rgb else None

        return {
            "dominant": dominant_hex,
            "vibrant": _rgb_to_hex(*vibrant_rgb) if vibrant_rgb else None,
            "source": "screenshot",
        }
    except Exception:
        return {
            "dominant": [],
            "vibrant": None,
            "source": "screenshot-error",
        }


def extract_image_palette(page):
    dom_palette = extract_image_palette_from_dom(page)

    if (dom_palette or {}).get("dominant"):
        return dom_palette

    return extract_image_palette_from_screenshot(page)
