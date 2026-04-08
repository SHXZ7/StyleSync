import asyncio
import math
from concurrent.futures import ThreadPoolExecutor

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from services.image_analysis import extract_image_palette

executor = ThreadPoolExecutor(max_workers=2)


def clean_fonts(fonts):
  cleaned = []
  seen = set()

  for f in fonts:
    name = str(f.get("value", "")).split(",")[0].strip().strip('"').strip("'")
    if not name:
      continue

    lower = name.lower()

    # remove junk/icon/fallback families
    if "icon" in lower:
      continue
    if lower in ["sans-serif", "serif", "monospace"]:
      continue

    # deduplicate by normalized key
    key = "".join(ch for ch in lower if ch.isalnum())
    if key in seen:
      continue

    seen.add(key)
    cleaned.append(name)

  return cleaned[:2]


def _size_value_to_px(size_value):
  raw = str(size_value).strip().lower().replace("px", "")
  try:
    return float(raw)
  except ValueError:
    return None


def _meaningful_sizes(entries, min_delta=2.0):
  deduped = []
  for entry in sorted(entries, key=lambda x: x["px"], reverse=True):
    if all(abs(entry["px"] - existing["px"]) >= min_delta for existing in deduped):
      deduped.append(entry)
  return deduped


def _step_typography_defaults(step, body_weight=400):
  if step == "display":
    return {"weight": 700, "line_height": 1.0, "letter_spacing": "-0.03em"}
  if step == "h1":
    return {"weight": 700, "line_height": 1.1, "letter_spacing": "-0.02em"}
  if step == "h2":
    return {"weight": 600, "line_height": 1.15, "letter_spacing": "-0.015em"}
  if step == "h3":
    return {"weight": 600, "line_height": 1.2, "letter_spacing": "-0.01em"}
  if step == "h4":
    return {"weight": 600, "line_height": 1.25, "letter_spacing": "-0.005em"}
  if step == "small":
    return {"weight": 400, "line_height": 1.4, "letter_spacing": "0em"}
  if step == "caption":
    return {"weight": 400, "line_height": 1.3, "letter_spacing": "0.01em"}
  return {"weight": body_weight, "line_height": 1.5, "letter_spacing": "0em"}


def build_type_scale(font_sizes, body_size, body_weight=400):
  entries = []
  for item in font_sizes:
    px = _size_value_to_px(item.get("value", ""))
    if px is None:
      continue
    entries.append({
      "value": item.get("value"),
      "px": px,
      "count": item.get("count", 0),
    })

  if not entries:
    return []

  clean_sizes = _meaningful_sizes(entries)

  body_px = _size_value_to_px(body_size)
  body_entry = None
  if body_px is not None:
    body_entry = min(clean_sizes, key=lambda x: abs(x["px"] - body_px))
  else:
    body_entry = max(entries, key=lambda x: x["count"])

  above = [s for s in clean_sizes if s["px"] > body_entry["px"]]
  below = [s for s in clean_sizes if s["px"] < body_entry["px"]]

  above = sorted(above, key=lambda x: x["px"], reverse=True)
  below = sorted(below, key=lambda x: x["px"], reverse=True)

  scale = []
  for step, item in zip(["display", "h1", "h2", "h3", "h4"], above[:5]):
    defaults = _step_typography_defaults(step, body_weight)
    scale.append({
      "step": step,
      "size": item["value"],
      "weight": defaults["weight"],
      "line_height": defaults["line_height"],
      "letter_spacing": defaults["letter_spacing"],
    })

  body_defaults = _step_typography_defaults("body", body_weight)
  scale.append({
    "step": "body",
    "size": body_entry["value"],
    "weight": body_defaults["weight"],
    "line_height": body_defaults["line_height"],
    "letter_spacing": body_defaults["letter_spacing"],
  })

  for step, item in zip(["small", "caption"], below[:2]):
    defaults = _step_typography_defaults(step, body_weight)
    scale.append({
      "step": step,
      "size": item["value"],
      "weight": defaults["weight"],
      "line_height": defaults["line_height"],
      "letter_spacing": defaults["letter_spacing"],
    })

  # Ensure caption exists even when the page has a narrow size range.
  if not any(item.get("step") == "caption" for item in scale):
    smallest = min(entries, key=lambda x: x["px"])
    caption_size = smallest["value"]
    defaults = _step_typography_defaults("caption", body_weight)
    scale.append({
      "step": "caption",
      "size": caption_size,
      "weight": defaults["weight"],
      "line_height": defaults["line_height"],
      "letter_spacing": defaults["letter_spacing"],
    })

  return scale


def build_typography_tokens(raw_typography):
  fonts = raw_typography.get("font_families", [])
  font_sizes = raw_typography.get("font_sizes", [])
  font_weights = raw_typography.get("font_weights", [])

  body_size = None
  if font_sizes:
    body_size = max(font_sizes, key=lambda x: x.get("count", 0)).get("value")

  body_weight = 400
  if font_weights:
    dominant = max(font_weights, key=lambda x: x.get("count", 0)).get("value", "400")
    try:
      body_weight = int(dominant)
    except (TypeError, ValueError):
      body_weight = 400

  fonts = clean_fonts(fonts)
  primary_font = fonts[0] if fonts else None

  return {
    "font_family": [primary_font] if primary_font else [],
    "primary_font": primary_font,
    "body_size": body_size,
    "scale": build_type_scale(font_sizes, body_size, body_weight),
  }


def _gcd_list(values):
  current = 0
  for v in values:
    current = math.gcd(current, int(v))
  return current


def normalize_spacing(scale, base=4):
  if base <= 0:
    base = 4
  return sorted(set(int(round(s / base) * base) for s in scale if s > 0))


def reduce_spacing_scale(scale, base=4):
  if not scale:
    return [base, base * 2, base * 4, base * 6]

  normalized = normalize_spacing(scale, base=base)
  preferred = [base, base * 2, base * 4, base * 6, base * 8, base * 10]

  reduced = [value for value in preferred if value in normalized]

  if len(reduced) < 4:
    for value in normalized:
      if value not in reduced:
        reduced.append(value)
      if len(reduced) >= 4:
        break

  return sorted(set(reduced))


def build_spacing_tokens(raw_spacing):
  spacing_values = raw_spacing.get("values", [])

  numeric = []
  for item in spacing_values:
    px = _size_value_to_px(item.get("value", ""))
    if px is None:
      continue

    rounded = int(round(px))
    if 2 <= rounded <= 128:
      numeric.append((rounded, item.get("count", 0)))

  if not numeric:
    return {
      "base": 4,
      "scale": [4, 8, 16, 32],
    }

  expanded = []
  for value, count in numeric:
    expanded.extend([value] * max(1, min(count, 10)))

  base = _gcd_list(expanded)
  if base < 2 or base > 16:
    by_freq = sorted(numeric, key=lambda x: x[1], reverse=True)
    candidate = by_freq[0][0] if by_freq else 4
    if candidate % 4 == 0:
      base = 4
    elif candidate % 8 == 0:
      base = 8
    else:
      base = 4

  unique_sizes = sorted({value for value, _ in numeric})
  meaningful = []
  for value in unique_sizes:
    if value < base:
      continue
    if all(abs(value - existing) >= base for existing in meaningful):
      meaningful.append(value)

  scale = meaningful[:6]
  if not scale:
    scale = [base, base * 2, base * 4, base * 8]

  scale = reduce_spacing_scale(scale, base=base)

  return {
    "base": base,
    "scale": scale,
  }


def _scrape_sync(url: str):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(url, timeout=60000, wait_until="domcontentloaded")

        # Some pages keep long-lived network requests open, so networkidle can timeout.
        try:
            page.wait_for_load_state("networkidle", timeout=10000)
        except PlaywrightTimeoutError:
            pass

        # Small settle period to allow late-applied styles.
        page.wait_for_timeout(750)

        colors = page.evaluate(
            """
            () => {
              const colorMap = new Map();
              const skip = new Set([
                "transparent",
                "none",
                "inherit",
                "initial",
                "unset",
                "currentcolor",
                "rgba(0, 0, 0, 0)",
                "rgb(0, 0, 0, 0)",
              ]);

              const resolver = document.createElement("span");
              resolver.style.display = "none";
              (document.body || document.documentElement).appendChild(resolver);

              const normalizeColor = (value) => {
                if (!value) return null;
                const raw = String(value).trim();
                if (!raw) return null;

                const rawLower = raw.toLowerCase();
                if (skip.has(rawLower)) return null;

                resolver.style.color = "";
                resolver.style.color = raw;

                // Invalid color syntax.
                if (!resolver.style.color) return null;

                // Computed style resolves var(--token) and named colors.
                const normalized = window.getComputedStyle(resolver).color.trim().toLowerCase();
                if (!normalized || skip.has(normalized)) return null;

                // Drop fully transparent colors.
                if (normalized.startsWith("rgba(")) {
                  const rgba = normalized
                    .slice(5, -1)
                    .split(",")
                    .map((p) => p.trim());
                  if (rgba.length === 4 && Number(rgba[3]) === 0) return null;
                }

                return normalized;
              };

              const addColor = (value, source, weight = 1) => {
                if (!value) return;
                const trimmed = String(value).trim();
                if (!trimmed) return;

                const embedded = trimmed.match(/#[0-9a-fA-F]{3,8}|rgba?\([^\)]*\)|hsla?\([^\)]*\)/g);
                if (embedded && embedded.length > 1) {
                  embedded.forEach((piece) => addColor(piece, source, weight));
                  return;
                }

                const normalized = normalizeColor(trimmed);
                if (!normalized) return;

                const key = normalized;
                const prev = colorMap.get(key) || {
                  value: normalized,
                  count: 0,
                  sources: new Set(),
                };
                prev.count += weight;
                prev.sources.add(source);
                colorMap.set(key, prev);
              };

              const collectFromElement = (el, source, weight = 1) => {
                const style = window.getComputedStyle(el);
                addColor(style.color, source + ":text", weight);
                addColor(style.backgroundColor, source + ":bg", weight);
                addColor(style.borderTopColor, source + ":border", weight);
                addColor(style.borderRightColor, source + ":border", weight);
                addColor(style.borderBottomColor, source + ":border", weight);
                addColor(style.borderLeftColor, source + ":border", weight);
                addColor(style.outlineColor, source + ":outline", weight);
                addColor(style.fill, source + ":fill", weight);
                addColor(style.stroke, source + ":stroke", weight);
              };

              const isSocialAuthButton = (el) => {
                const text = (el.innerText || el.textContent || "").toLowerCase();
                const attrs = [
                  el.getAttribute("aria-label") || "",
                  el.getAttribute("title") || "",
                  el.getAttribute("class") || "",
                  el.getAttribute("id") || "",
                  el.getAttribute("href") || "",
                ]
                  .join(" ")
                  .toLowerCase();

                const haystack = `${text} ${attrs}`;
                return ["google", "facebook", "apple", "linkedin", "github", "oauth", "signin", "sign in with"].some((k) =>
                  haystack.includes(k)
                );
              };

              const collectCssVariables = () => {
                const seen = new Set();

                const collectStyleVars = (styleDecl, source) => {
                  if (!styleDecl) return;
                  for (let i = 0; i < styleDecl.length; i++) {
                    const name = styleDecl[i];
                    if (!name || !name.startsWith("--") || seen.has(name)) continue;

                    const value = styleDecl.getPropertyValue(name);
                    if (!value) continue;

                    seen.add(name);
                    addColor(value, source + ":" + name);
                  }
                };

                // Root custom properties are often brand tokens.
                collectStyleVars(window.getComputedStyle(document.documentElement), "css-var-root");

                // Read custom properties defined in same-origin stylesheets.
                for (const sheet of Array.from(document.styleSheets)) {
                  let rules;
                  try {
                    rules = sheet.cssRules;
                  } catch {
                    continue;
                  }

                  for (const rule of Array.from(rules || [])) {
                    if (rule && rule.style) {
                      collectStyleVars(rule.style, "css-var-sheet");
                    }
                  }
                }
              };

              collectCssVariables();

              document
                .querySelectorAll('button, [role="button"], input[type="button"], input[type="submit"], input[type="reset"]')
                .forEach((el) => {
                  const weight = isSocialAuthButton(el) ? 0.2 : 1;
                  collectFromElement(el, "button", weight);
                });

              document
                .querySelectorAll("a[href]")
                .forEach((el) => collectFromElement(el, "link"));

              document.querySelectorAll("*").forEach((el) => {
                const style = window.getComputedStyle(el);
                const hasBorder =
                  parseFloat(style.borderTopWidth || "0") > 0 ||
                  parseFloat(style.borderRightWidth || "0") > 0 ||
                  parseFloat(style.borderBottomWidth || "0") > 0 ||
                  parseFloat(style.borderLeftWidth || "0") > 0 ||
                  parseFloat(style.outlineWidth || "0") > 0;

                if (hasBorder) {
                  addColor(style.borderTopColor, "border");
                  addColor(style.borderRightColor, "border");
                  addColor(style.borderBottomColor, "border");
                  addColor(style.borderLeftColor, "border");
                  addColor(style.outlineColor, "border");
                }
              });

              document.querySelectorAll("svg, svg *").forEach((el) => {
                const style = window.getComputedStyle(el);
                addColor(style.fill, "svg");
                addColor(style.stroke, "svg");
                addColor(el.getAttribute("fill"), "svg-attr");
                addColor(el.getAttribute("stroke"), "svg-attr");
              });

              const ranked = Array.from(colorMap.values())
                .sort((a, b) => {
                  const scoreA = a.count + a.sources.size;
                  const scoreB = b.count + b.sources.size;
                  return scoreB - scoreA;
                })
                .map((entry) => entry.value);

              resolver.remove();
              return ranked;
            }
            """
        )

        typography = page.evaluate(
            """
            () => {
              const elements = Array.from(document.querySelectorAll("*"));

              const countBy = (map, value) => {
                if (!value) return;
                const key = String(value).trim();
                if (!key) return;
                map.set(key, (map.get(key) || 0) + 1);
              };

              const fallbackFamilies = new Set([
                "serif",
                "sans-serif",
                "monospace",
                "cursive",
                "fantasy",
                "system-ui",
                "ui-sans-serif",
                "ui-serif",
                "ui-monospace",
                "inherit",
                "initial",
                "unset",
              ]);

              const isIconLikeFamily = (name) => {
                const lower = name.toLowerCase();
                return (
                  lower.includes("icon") ||
                  lower.includes("glyph") ||
                  lower.includes("fontawesome") ||
                  lower.includes("material symbols") ||
                  lower.includes("emoji") ||
                  lower.includes("symbol")
                );
              };

              const canonicalFamilyKey = (name) =>
                name
                  .toLowerCase()
                  .replace(/['"]/g, "")
                  .replace(/[^a-z0-9]/g, "");

              const parsePx = (value) => {
                if (!value) return null;
                const num = Number.parseFloat(value);
                return Number.isFinite(num) ? num : null;
              };

              const parseWeight = (value) => {
                const raw = String(value || "").trim().toLowerCase();
                if (!raw) return null;
                if (raw === "normal") return "400";
                if (raw === "bold" || raw === "bolder") return "700";
                if (raw === "lighter") return "300";
                const numeric = Number.parseInt(raw, 10);
                if (Number.isFinite(numeric)) return String(numeric);
                return null;
              };

              const familyMap = new Map();
              const familyVariants = new Map();
              const sizeMap = new Map();
              const weightMap = new Map();
              const lineHeightMap = new Map();

              elements.forEach((el) => {
                const style = window.getComputedStyle(el);

                const families = (style.fontFamily || "")
                  .split(",")
                  .map((f) => f.replace(/["']/g, "").trim())
                  .filter(Boolean);

                const chosenFamily = families.find((name) => {
                  const lower = name.toLowerCase();
                  if (fallbackFamilies.has(lower)) return false;
                  if (isIconLikeFamily(lower)) return false;
                  return true;
                });

                if (chosenFamily) {
                  const key = canonicalFamilyKey(chosenFamily);
                  if (key) {
                    familyMap.set(key, (familyMap.get(key) || 0) + 1);
                    const variants = familyVariants.get(key) || new Map();
                    variants.set(chosenFamily, (variants.get(chosenFamily) || 0) + 1);
                    familyVariants.set(key, variants);
                  }
                }

                const sizePx = parsePx(style.fontSize);
                if (sizePx && sizePx >= 10 && sizePx <= 120) {
                  const rounded = Math.round(sizePx * 10) / 10;
                  countBy(sizeMap, `${rounded}px`);
                }

                const weight = parseWeight(style.fontWeight);
                if (weight) {
                  countBy(weightMap, weight);
                }

                const lineHeight = style.lineHeight || "";
                if (lineHeight && lineHeight !== "normal") {
                  const lineHeightPx = parsePx(lineHeight);
                  if (lineHeightPx) {
                    const rounded = Math.round(lineHeightPx * 10) / 10;
                    countBy(lineHeightMap, `${rounded}px`);
                  }
                }
              });

              const toReadableFamily = (familyKey) => {
                const variants = familyVariants.get(familyKey);
                if (!variants) return familyKey;

                return Array.from(variants.entries())
                  .sort((a, b) => b[1] - a[1])[0][0];
              };

              const toSortedArray = (map) =>
                Array.from(map.entries())
                  .sort((a, b) => b[1] - a[1])
                  .map(([value, count]) => ({ value, count }));

              const sizeEntries = Array.from(sizeMap.entries())
                .map(([value, count]) => ({
                  value,
                  count,
                  px: Number.parseFloat(value),
                }))
                .filter((item) => Number.isFinite(item.px));

              const clustered = [];
              const sortedByPx = [...sizeEntries].sort((a, b) => b.px - a.px);
              sortedByPx.forEach((entry) => {
                const cluster = clustered.find((c) => Math.abs(c.px - entry.px) <= 1);
                if (!cluster) {
                  clustered.push({
                    px: entry.px,
                    count: entry.count,
                    samples: [entry.value],
                  });
                  return;
                }

                cluster.px = (cluster.px * cluster.count + entry.px * entry.count) / (cluster.count + entry.count);
                cluster.count += entry.count;
                cluster.samples.push(entry.value);
              });

              const clusteredSizes = clustered
                .map((c) => ({
                  px: Math.round(c.px * 10) / 10,
                  count: c.count,
                  value: `${Math.round(c.px * 10) / 10}px`,
                }))
                .sort((a, b) => b.count - a.count);

              const bodyCluster = clusteredSizes[0] || null;
              const bySizeDesc = [...clusteredSizes].sort((a, b) => b.px - a.px);

              let bodyIdx = -1;
              if (bodyCluster) {
                bodyIdx = bySizeDesc.findIndex((s) => Math.abs(s.px - bodyCluster.px) <= 0.2);
              }

              const above = bodyIdx >= 0 ? bySizeDesc.slice(0, bodyIdx) : bySizeDesc.slice(0, 4);
              const below = bodyIdx >= 0 ? bySizeDesc.slice(bodyIdx + 1) : [];

              const typeScale = [];
              const pushStep = (step, item) => {
                if (!item) return;
                typeScale.push({
                  step,
                  size: item.value,
                  count: item.count,
                });
              };

              pushStep("display", above[0]);
              pushStep("h1", above[1]);
              pushStep("h2", above[2]);
              pushStep("h3", above[3]);
              if (bodyCluster) pushStep("body", bodyCluster);
              pushStep("small", below[0]);
              pushStep("caption", below[1]);

              const familyResult = Array.from(familyMap.entries())
                .sort((a, b) => b[1] - a[1])
                .map(([key, count]) => ({
                  value: toReadableFamily(key),
                  count,
                }))
                .slice(0, 8);

              return {
                font_families: familyResult,
                font_sizes: clusteredSizes
                  .sort((a, b) => b.count - a.count)
                  .slice(0, 10)
                  .map((item) => ({ value: item.value, count: item.count })),
                font_weights: toSortedArray(weightMap).slice(0, 8),
                line_heights: toSortedArray(lineHeightMap).slice(0, 8),
                type_scale: typeScale,
              };
            }
            """
        )

        spacing = page.evaluate(
            """
            () => {
              const elements = Array.from(document.querySelectorAll("*"));

              const spacingMap = new Map();

              const addSpacing = (value) => {
                if (!value) return;
                const raw = String(value).trim().toLowerCase();
                if (!raw || raw === "0px" || raw === "0") return;

                const parsed = Number.parseFloat(raw);
                if (!Number.isFinite(parsed)) return;

                const normalized = `${Math.round(parsed * 10) / 10}px`;
                spacingMap.set(normalized, (spacingMap.get(normalized) || 0) + 1);
              };

              elements.forEach((el) => {
                const style = window.getComputedStyle(el);

                addSpacing(style.paddingTop);
                addSpacing(style.paddingRight);
                addSpacing(style.paddingBottom);
                addSpacing(style.paddingLeft);

                addSpacing(style.marginTop);
                addSpacing(style.marginRight);
                addSpacing(style.marginBottom);
                addSpacing(style.marginLeft);

                addSpacing(style.rowGap);
                addSpacing(style.columnGap);
                addSpacing(style.gap);
              });

              const values = Array.from(spacingMap.entries())
                .sort((a, b) => b[1] - a[1])
                .map(([value, count]) => ({ value, count }))
                .slice(0, 20);

              return { values };
            }
            """
        )

        buttons = page.evaluate(
            """
            () => {
              const buttonMap = new Map();

              const selectors = "button, a[role='button'], input[type='button'], input[type='submit'], a[class*='btn'], a[class*='button'], button[class*='btn'], button[class*='button']";
              document.querySelectorAll(selectors).forEach((el) => {
                const text = (el.innerText || el.textContent || "").toLowerCase();
                const attrs = [
                  el.getAttribute("aria-label") || "",
                  el.getAttribute("title") || "",
                  el.getAttribute("class") || "",
                  el.getAttribute("id") || "",
                  el.getAttribute("href") || "",
                ]
                  .join(" ")
                  .toLowerCase();
                const haystack = `${text} ${attrs}`;
                const isSocialAuth = ["google", "facebook", "apple", "linkedin", "github", "oauth", "sign in with", "continue with"].some((k) =>
                  haystack.includes(k)
                );
                if (isSocialAuth) return;

                const style = window.getComputedStyle(el);

                const bg = style.backgroundColor;
                const color = style.color;
                const padding = style.padding;
                const radius = style.borderRadius;
                const borderColor = style.borderTopColor;
                const borderWidth = style.borderTopWidth;
                const borderStyle = style.borderTopStyle;
                const fontSize = style.fontSize;
                const fontWeight = style.fontWeight;

                const key = `${bg}-${color}-${padding}-${radius}-${borderColor}-${borderWidth}-${borderStyle}-${fontSize}-${fontWeight}`;

                if (!buttonMap.has(key)) {
                  buttonMap.set(key, {
                    background: bg,
                    text: color,
                    padding,
                    radius,
                    borderColor,
                    borderWidth,
                    borderStyle,
                    fontSize,
                    fontWeight,
                    count: 0,
                  });
                }

                buttonMap.get(key).count += 1;
              });

              return Array.from(buttonMap.values())
                .sort((a, b) => b.count - a.count)
                .slice(0, 5);
            }
            """
        )

        image_palette = extract_image_palette(page)

        social_auth_colors = page.evaluate(
            """
            () => {
              const skip = new Set([
                "transparent",
                "none",
                "inherit",
                "initial",
                "unset",
                "currentcolor",
                "rgba(0, 0, 0, 0)",
                "rgb(0, 0, 0, 0)",
              ]);

              const resolver = document.createElement("span");
              resolver.style.display = "none";
              (document.body || document.documentElement).appendChild(resolver);

              const normalizeColor = (value) => {
                if (!value) return null;
                const raw = String(value).trim();
                if (!raw) return null;

                resolver.style.color = "";
                resolver.style.color = raw;
                if (!resolver.style.color) return null;

                const normalized = window.getComputedStyle(resolver).color.trim().toLowerCase();
                if (!normalized || skip.has(normalized)) return null;
                if (normalized.startsWith("rgba(")) {
                  const rgba = normalized
                    .slice(5, -1)
                    .split(",")
                    .map((p) => p.trim());
                  if (rgba.length === 4 && Number(rgba[3]) === 0) return null;
                }
                return normalized;
              };

              const isSocial = (el) => {
                const text = (el.innerText || el.textContent || "").toLowerCase();
                const attrs = [
                  el.getAttribute("aria-label") || "",
                  el.getAttribute("title") || "",
                  el.getAttribute("class") || "",
                  el.getAttribute("id") || "",
                  el.getAttribute("href") || "",
                ]
                  .join(" ")
                  .toLowerCase();
                const haystack = `${text} ${attrs}`;
                return ["google", "oauth", "social", "sign in with", "continue with"].some((k) => haystack.includes(k));
              };

              const found = new Set();
              document.querySelectorAll("button, a, [role='button'], form, div, section").forEach((el) => {
                if (!isSocial(el)) return;
                const style = window.getComputedStyle(el);
                [style.color, style.backgroundColor, style.borderTopColor, style.borderRightColor, style.borderBottomColor, style.borderLeftColor]
                  .map(normalizeColor)
                  .filter(Boolean)
                  .forEach((c) => found.add(c));
              });

              resolver.remove();
              return Array.from(found).slice(0, 20);
            }
            """
        )

        error_colors = page.evaluate(
            """
            () => {
              const selectors = [
                "[class*='error']",
                "[class*='alert']",
                "[class*='danger']",
                "[role='alert']",
                "[aria-invalid='true']",
                "input:invalid",
                "textarea:invalid",
              ].join(",");

              const nodes = Array.from(document.querySelectorAll(selectors)).slice(0, 120);
              const colors = new Set();

              const skip = new Set([
                "transparent",
                "none",
                "inherit",
                "initial",
                "unset",
                "currentcolor",
                "rgba(0, 0, 0, 0)",
                "rgb(0, 0, 0, 0)",
              ]);

              const resolver = document.createElement("span");
              resolver.style.display = "none";
              (document.body || document.documentElement).appendChild(resolver);

              const normalizeColor = (value) => {
                if (!value) return null;
                const raw = String(value).trim();
                if (!raw) return null;

                resolver.style.color = "";
                resolver.style.color = raw;
                if (!resolver.style.color) return null;

                const normalized = window.getComputedStyle(resolver).color.trim().toLowerCase();
                if (!normalized || skip.has(normalized)) return null;
                if (normalized.startsWith("rgba(")) {
                  const rgba = normalized
                    .slice(5, -1)
                    .split(",")
                    .map((p) => p.trim());
                  if (rgba.length === 4 && Number(rgba[3]) === 0) return null;
                }
                return normalized;
              };

              nodes.forEach((el) => {
                const style = window.getComputedStyle(el);
                [style.color, style.backgroundColor, style.borderTopColor, style.borderRightColor, style.borderBottomColor, style.borderLeftColor]
                  .map(normalizeColor)
                  .filter(Boolean)
                  .forEach((c) => colors.add(c));
              });

              resolver.remove();
              return Array.from(colors).slice(0, 20);
            }
            """
        )

        typography = build_typography_tokens(typography)
        spacing = build_spacing_tokens(spacing)

        browser.close()
        return {
            "colors": colors,
            "typography": typography,
            "spacing": spacing,
            "buttons": buttons,
            "image_palette": image_palette,
            "image_palette_source": image_palette.get("source"),
            "image_palette_confidence": image_palette.get("confidence", 0),
            "image_palette_sampled_images": image_palette.get("sampled_images", 0),
            "social_auth_colors": social_auth_colors,
            "error_colors": error_colors,
        }



async def scrape_colors(url: str):
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(executor, _scrape_sync, url)
    return result.get("colors", [])


async def scrape_design(url: str):
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(executor, _scrape_sync, url)
    return result
