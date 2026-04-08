"use client";

import { useState } from "react";

export default function Home() {
  const apiBase = process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8000";
  const apiUrl = (path) => `${apiBase}${path}`;

  const [url, setUrl] = useState("");
  const [result, setResult] = useState(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState("");
  const [editableColors, setEditableColors] = useState({});
  const [editableTypography, setEditableTypography] = useState({
    fontFamily: "Inter, sans-serif",
    bodySize: 14,
    bodyWeight: 400,
    bodyLineHeight: 1.5,
    h1Size: 40,
  });
  const [editableSpacing, setEditableSpacing] = useState({
    xs: 4,
    sm: 8,
    md: 16,
    lg: 24,
  });
  const [previewTab, setPreviewTab] = useState("button");
  const [lockedTokens, setLockedTokens] = useState({});
  const [isSavingState, setIsSavingState] = useState(false);

  const tokenValue = (token) => (token && typeof token === "object" && "value" in token ? token.value : token);

  const bootstrapEditableColors = (systemColors) => {
    if (!systemColors) {
      return {};
    }

    const entries = Object.entries(systemColors)
      .filter(([name]) => name !== "neutrals")
      .map(([name, value]) => [name, tokenValue(value)]);

    const mapped = {};
    entries.forEach(([name, value]) => {
      mapped[name] = typeof value === "string" ? value : "";
    });
    return mapped;
  };

  const toLockedMap = (lockedList) => {
    const mapped = {};
    (lockedList || []).forEach((token) => {
      mapped[token] = true;
    });
    return mapped;
  };

  const toPxNumber = (value, fallback) => {
    const raw = String(value ?? "").replace("px", "").trim();
    const parsed = Number(raw);
    return Number.isFinite(parsed) ? parsed : fallback;
  };

  const bootstrapEditableTypography = (systemTypography) => {
    const base = {
      fontFamily: tokenValue((systemTypography?.font_family || [])[0]) || "Inter, sans-serif",
      bodySize: toPxNumber(tokenValue(systemTypography?.body_size), 14),
      bodyWeight: 400,
      bodyLineHeight: 1.5,
      h1Size: 40,
    };

    const scale = systemTypography?.scale || [];
    const bodyStep = scale.find((step) => step.step === "body");
    const h1Step = scale.find((step) => step.step === "h1");

    if (bodyStep) {
      base.bodySize = toPxNumber(tokenValue(bodyStep.size), base.bodySize);
      base.bodyWeight = Number(tokenValue(bodyStep.weight) || base.bodyWeight);
      base.bodyLineHeight = Number(tokenValue(bodyStep.line_height) || base.bodyLineHeight);
    }
    if (h1Step) {
      base.h1Size = toPxNumber(tokenValue(h1Step.size), base.h1Size);
    }

    return base;
  };

  const bootstrapEditableSpacing = (systemSpacing) => ({
    xs: Number(tokenValue(systemSpacing?.xs) || 4),
    sm: Number(tokenValue(systemSpacing?.sm) || 8),
    md: Number(tokenValue(systemSpacing?.md) || 16),
    lg: Number(tokenValue(systemSpacing?.lg) || 24),
  });

  const buildThemeVars = () => ({
    "--color-primary": getLiveColor("primary", colors?.primary),
    "--color-primary-foreground": getLiveColor("primary_foreground", colors?.primary_foreground),
    "--color-surface": getLiveColor("surface", colors?.surface),
    "--color-surface-alt": getLiveColor("surface_alt", colors?.surface_alt),
    "--color-text-primary": getLiveColor("text_primary", colors?.text_primary),
    "--color-text-secondary": getLiveColor("text_secondary", colors?.text_secondary),
    "--color-brand": getLiveColor("brand", colors?.brand),
    "--color-danger": getLiveColor("danger", colors?.danger),
    "--font-family-base": editableTypography.fontFamily,
    "--font-size-body": `${editableTypography.bodySize}px`,
    "--font-size-h1": `${editableTypography.h1Size}px`,
    "--font-weight-body": String(editableTypography.bodyWeight),
    "--line-height-body": String(editableTypography.bodyLineHeight),
    "--spacing-xs": `${editableSpacing.xs}px`,
    "--spacing-sm": `${editableSpacing.sm}px`,
    "--spacing-md": `${editableSpacing.md}px`,
    "--spacing-lg": `${editableSpacing.lg}px`,
  });

  const exportPayload = () => ({
    colors: editableColors,
    typography: editableTypography,
    spacing: editableSpacing,
    lockedTokens: Object.entries(lockedTokens)
      .filter(([, v]) => Boolean(v))
      .map(([k]) => k),
  });

  const downloadText = (filename, text) => {
    const blob = new Blob([text], { type: "text/plain;charset=utf-8" });
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = filename;
    link.click();
    URL.revokeObjectURL(link.href);
  };

  const persistThemeState = async (nextLocked, nextColors, nextTypography, nextSpacing) => {
    const validUrl = safeUrl(url.trim());
    if (!validUrl) {
      return;
    }

    const lockedList = Object.entries(nextLocked || {})
      .filter(([, isLocked]) => Boolean(isLocked))
      .map(([token]) => token);

    setIsSavingState(true);
    try {
      const res = await fetch(apiUrl("/theme-state"), {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          url: validUrl,
          locked_tokens: lockedList,
          overrides: {
            colors: nextColors || {},
            typography: nextTypography || editableTypography,
            spacing: nextSpacing || editableSpacing,
          },
        }),
      });

      if (res.ok) {
        const stateData = await res.json();
        setResult((prev) => {
          if (!prev) {
            return prev;
          }
          return {
            ...prev,
            state: stateData,
            meta: {
              ...(prev.meta || {}),
              version: stateData.version,
              locked_tokens: stateData.locked_tokens || [],
            },
          };
        });
      }
    } catch {
      // Keep UI responsive even if persistence fails.
    } finally {
      setIsSavingState(false);
    }
  };

  const safeUrl = (raw) => {
    try {
      const parsed = new URL(raw);
      return parsed.toString();
    } catch {
      return null;
    }
  };

  const handleAnalyze = async () => {
    const validUrl = safeUrl(url.trim());
    if (!validUrl) {
      setError("Enter a valid URL, for example https://www.example.com");
      setResult(null);
      return;
    }

    setIsLoading(true);
    setError("");

    try {
      const res = await fetch(apiUrl("/scrape?url=") + encodeURIComponent(validUrl), {
        method: "POST",
      });

      if (!res.ok) {
        const text = await res.text();
        throw new Error(text || `Request failed with status ${res.status}`);
      }

      const data = await res.json();
      setResult(data);
      const loadedColors = {
        ...bootstrapEditableColors(data?.system?.colors),
        ...((data?.state?.overrides || {}).colors || {}),
      };
      setEditableColors(loadedColors);
      setEditableTypography({
        ...bootstrapEditableTypography(data?.system?.typography),
        ...((data?.state?.overrides || {}).typography || {}),
      });
      setEditableSpacing({
        ...bootstrapEditableSpacing(data?.system?.spacing),
        ...((data?.state?.overrides || {}).spacing || {}),
      });
      setLockedTokens(toLockedMap(data?.state?.locked_tokens));
    } catch (err) {
      const message = String(err?.message || "Unknown error");
      if (message.toLowerCase().includes("cors") || message.toLowerCase().includes("failed to fetch")) {
        setError("This site blocks scanners or cross-origin requests. Try another public URL or enter tokens manually.");
      } else {
        setError("We could not scan this URL. Check the link format and try again.");
      }
      setResult(null);
    } finally {
      setIsLoading(false);
    }
  };

  const system = result?.system;
  const colors = system?.colors;
  const typography = system?.typography;
  const spacing = system?.spacing;
  const radii = system?.radii;
  const imagePalette = system?.image_palette;
  const meta = result?.meta;
  const components = system?.components;

  const getLiveColor = (name, fallback) => editableColors[name] || tokenValue(fallback) || "#000000";

  const toggleLock = (tokenName) => {
    setLockedTokens((prev) => {
      const next = {
        ...prev,
        [tokenName]: !prev[tokenName],
      };
      persistThemeState(next, editableColors, editableTypography, editableSpacing);
      return next;
    });
  };

  const updateColor = (tokenName, colorName, value) => {
    if (lockedTokens[tokenName]) {
      return;
    }
    setEditableColors((prev) => ({
      ...prev,
      [colorName]: value,
    }));

    const nextColors = {
      ...editableColors,
      [colorName]: value,
    };
    persistThemeState(lockedTokens, nextColors, editableTypography, editableSpacing);
  };

  const infoCards = [
    {
      title: "Extract Colors",
      body: "Intelligent color palette extraction from CSS and page imagery.",
      icon: "●",
      iconClass: "text-[#ff3b30]",
    },
    {
      title: "Typography Scale",
      body: "Detect font families, hierarchy, and type rhythm across UI.",
      icon: "Aa",
      iconClass: "text-[#2563eb]",
    },
    {
      title: "Spacing Tokens",
      body: "Analyze spacing rhythm for reusable layout token sets.",
      icon: "▰",
      iconClass: "text-[#eab308]",
    },
  ];

  const metricItems = [
    ["style", meta?.style || "-"],
    ["density", meta?.density || "-"],
    ["mode", meta?.color_mode || "-"],
    ["scrape", meta?.scrape_mode || "live"],
    ["image palette", meta?.image_palette_source || "dom-images"],
  ];

  const prettyLabel = (label) =>
    String(label)
      .replace(/_/g, " ")
      .replace(/\b\w/g, (c) => c.toUpperCase());

  const isBoldMood = meta?.style && String(meta.style).toLowerCase().includes("modern") && Boolean(colors?.brand);

  return (
    <main className={`${result ? "min-h-screen overflow-y-auto" : "min-h-screen overflow-y-auto sm:h-screen sm:overflow-hidden"} bg-background px-3 py-4 text-foreground sm:px-6 sm:py-5`}>
      <section className={`mx-auto flex w-full max-w-5xl flex-col gap-4 ${result ? "min-h-screen" : "h-full"}`}>
        <header className="text-center">
          <h1 className="display-title text-5xl leading-none text-[#050505] sm:text-8xl lg:text-8xl">STYLESYNC</h1>
          <p className="mt-1 text-xs font-semibold text-[#3f3f46] sm:text-lg">
            Transform any website into an interactive, living design system
          </p>
        </header>

        <div className="neo-frame hero-mosaic relative h-28 w-full overflow-hidden sm:h-40 lg:h-44" />

        <div className="w-full space-y-3">
          <div className="sticky top-0 z-20 -mx-3 bg-background/95 px-3 py-2 backdrop-blur-sm sm:static sm:mx-0 sm:bg-transparent sm:px-0 sm:py-0">
            <div className="flex w-full flex-col gap-2 sm:flex-row sm:gap-3">
            <input
              type="text"
              placeholder="https://www.upwork.com/"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              className="h-11 w-full border-2 border-[#050505] bg-[#f5f5f5] px-3 text-sm font-semibold text-[#0f172a] outline-none focus:border-[#ff3b30] sm:h-12 sm:px-4 sm:text-base"
            />
            <button
              onClick={handleAnalyze}
              disabled={isLoading}
              className="h-11 shrink-0 border-2 border-[#050505] bg-[#ff3b30] px-5 text-sm font-black tracking-[0.12em] text-[#050505] shadow-[4px_4px_0_#050505] transition-transform hover:-translate-y-0.5 active:translate-y-0 sm:h-12 sm:px-7 sm:text-base sm:tracking-[0.14em]"
            >
              {isLoading ? "PARSING..." : "SCAN SITE"}
            </button>
          </div>
          </div>

          <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
            {infoCards.map((card) => (
              <article key={card.title} className="neo-frame p-4 sm:p-5">
                <p className={`mb-1 text-2xl font-bold sm:text-3xl ${card.iconClass}`}>{card.icon}</p>
                <h2 className="mb-1 text-3xl font-black leading-none text-[#050505] sm:text-5xl">{card.title}</h2>
                <p className="text-xs font-medium leading-snug text-[#3f3f46] sm:text-sm">{card.body}</p>
              </article>
            ))}
          </div>
        </div>

      {isLoading && (
        <section className="neo-frame p-4">
          <p className="mb-3 text-sm font-black uppercase tracking-[0.16em] text-[#050505]">Parsing DOM Tree</p>
          <div className="space-y-2">
            <div className="h-3 w-1/2 animate-pulse bg-[#d4d4d8]" />
            <div className="ml-4 h-3 w-2/3 animate-pulse bg-[#e4e4e7]" />
            <div className="ml-8 h-3 w-1/3 animate-pulse bg-[#d4d4d8]" />
            <div className="ml-12 h-3 w-1/2 animate-pulse bg-[#e4e4e7]" />
            <div className="ml-4 h-3 w-3/4 animate-pulse bg-[#d4d4d8]" />
          </div>
          <div className="mt-4 grid grid-cols-3 gap-2">
            <div className="h-18 animate-pulse border border-[#050505] bg-[#efefef]" />
            <div className="h-18 animate-pulse border border-[#050505] bg-[#efefef]" />
            <div className="h-18 animate-pulse border border-[#050505] bg-[#efefef]" />
          </div>
        </section>
      )}

      {error && (
        <section className="neo-frame border-[#ff3b30] bg-[#fff1f0] p-4">
          <p className="text-sm font-black uppercase tracking-[0.16em] text-[#7f1d1d]">Scan Failed</p>
          <p className="mt-2 text-sm font-semibold text-[#7f1d1d]">{error}</p>
          <div className="mt-3 grid gap-2 text-xs text-[#7f1d1d] sm:grid-cols-3">
            <p className="border border-[#fecaca] bg-[#ffe4e6] px-2 py-1">Use full URL with https://</p>
            <p className="border border-[#fecaca] bg-[#ffe4e6] px-2 py-1">Try a public marketing page</p>
            <p className="border border-[#fecaca] bg-[#ffe4e6] px-2 py-1">Or start with manual token edits</p>
          </div>
        </section>
      )}

      {result && (
        <section className="mt-3 flex flex-col gap-3">
          <div className="neo-frame p-3">
            <p className="mb-2 text-sm font-black uppercase tracking-[0.2em] text-[#050505]">Scan Summary</p>
            <div className="grid grid-cols-1 gap-2 text-sm font-semibold text-[#27272a] sm:grid-cols-3">
              {metricItems.map(([label, value]) => (
                <div key={label} className="border border-[#050505] bg-[#ebebeb] px-3 py-2">
                  <p className="text-[11px] font-bold uppercase tracking-[0.08em] text-[#3f3f46]">{label}</p>
                  <p className="text-base font-black text-[#050505]">{String(value)}</p>
                </div>
              ))}
            </div>
            <div className="mt-2 text-xs font-semibold uppercase tracking-[0.08em] text-[#52525b]">
              Version {meta?.version || 0} {isSavingState ? "• Saving" : "• Saved"}
            </div>
            <div className="mt-2 flex flex-wrap gap-2">
              <button
                type="button"
                onClick={() => {
                  const vars = buildThemeVars();
                  const css = `:root {\n${Object.entries(vars)
                    .map(([k, v]) => `  ${k}: ${v};`)
                    .join("\n")}\n}`;
                  downloadText("stylesync-theme.css", css);
                }}
                className="border border-[#050505] bg-[#ebebeb] px-2 py-1 text-xs font-bold"
              >
                Export CSS Vars
              </button>
              <button
                type="button"
                onClick={() => {
                  downloadText("stylesync-tokens.json", JSON.stringify(exportPayload(), null, 2));
                }}
                className="border border-[#050505] bg-[#ebebeb] px-2 py-1 text-xs font-bold"
              >
                Export JSON
              </button>
              <button
                type="button"
                onClick={() => {
                  const p = exportPayload();
                  const tailwind = {
                    theme: {
                      extend: {
                        colors: p.colors,
                        spacing: Object.fromEntries(Object.entries(p.spacing).map(([k, v]) => [k, `${v}px`])),
                        fontFamily: {
                          base: [p.typography.fontFamily],
                        },
                      },
                    },
                  };
                  downloadText("stylesync-tailwind.config.json", JSON.stringify(tailwind, null, 2));
                }}
                className="border border-[#050505] bg-[#ebebeb] px-2 py-1 text-xs font-bold"
              >
                Export Tailwind
              </button>
            </div>
          </div>

          <div className="pr-1">

          {colors && (
            <div className={`neo-frame p-4 ${isBoldMood ? "ring-2 ring-[#ff3b30]/40" : ""}`}>
              <p className="mb-3 text-lg font-black uppercase tracking-[0.12em]">Token Editor</p>
              <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                {Object.entries(colors)
                  .filter(([name]) => name !== "neutrals")
                  .map(([name, value]) => {
                    const tokenName = `color.${name}`;
                    const isLocked = Boolean(lockedTokens[tokenName]);
                    const liveColor = getLiveColor(name, value);

                    return (
                      <div
                        key={name}
                        className={`border border-[#050505] bg-[#f5f5f5] p-2 transition-all duration-200 ${isLocked ? "shadow-[0_0_0_2px_rgba(255,59,48,0.35)]" : ""}`}
                      >
                        <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                          <p className="text-sm font-bold">{prettyLabel(name)}</p>
                          <div className="ml-auto flex items-center gap-2">
                            <span className="text-[10px] font-bold uppercase tracking-[0.08em] text-[#52525b]">
                              {isLocked ? "locked" : tokenValue(value?.source || value?.source) || "live"}
                            </span>
                            <button
                              type="button"
                              onClick={() => toggleLock(tokenName)}
                              className={`min-h-11 min-w-11 border border-[#050505] px-2 py-1 text-xs font-black transition-all duration-200 ${isLocked ? "bg-[#ffe4e6] text-[#7f1d1d]" : "bg-[#ebebeb]"}`}
                            >
                              <span className={`inline-block transition-transform duration-200 ${isLocked ? "scale-110" : "scale-100"}`}>
                                {isLocked ? "🔒" : "🔓"}
                              </span>
                            </button>
                          </div>
                        </div>
                        <div className="grid grid-cols-[48px_1fr] items-center gap-2">
                          <input
                            type="color"
                            value={liveColor}
                            disabled={isLocked}
                            onChange={(e) => updateColor(tokenName, name, e.target.value)}
                            className="h-9 w-12 cursor-pointer border border-[#050505] bg-white p-0"
                          />
                          <input
                            type="text"
                            value={liveColor}
                            disabled={isLocked}
                            onChange={(e) => updateColor(tokenName, name, e.target.value)}
                            className="h-9 border border-[#050505] bg-white px-2 font-mono text-xs"
                          />
                        </div>
                      </div>
                    );
                  })}
              </div>
            </div>
          )}

          {typography && (
            <div className="neo-frame p-4">
              <p className="mb-3 text-lg font-black uppercase tracking-[0.12em]">Typography Inspector</p>
              <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                <div className="border border-[#050505] bg-[#f5f5f5] p-3">
                  <label className="text-xs font-bold uppercase">Font Family</label>
                  <input
                    type="text"
                    value={editableTypography.fontFamily}
                    onChange={(e) => {
                      const next = { ...editableTypography, fontFamily: e.target.value };
                      setEditableTypography(next);
                      persistThemeState(lockedTokens, editableColors, next, editableSpacing);
                    }}
                    className="mt-1 h-9 w-full border border-[#050505] bg-white px-2 text-xs"
                  />

                  <div className="mt-2 grid grid-cols-2 gap-2 text-xs">
                    <label className="font-bold uppercase">Body Size</label>
                    <input
                      type="number"
                      value={editableTypography.bodySize}
                      onChange={(e) => {
                        const next = { ...editableTypography, bodySize: Number(e.target.value || 14) };
                        setEditableTypography(next);
                        persistThemeState(lockedTokens, editableColors, next, editableSpacing);
                      }}
                      className="h-8 border border-[#050505] bg-white px-2"
                    />
                    <label className="font-bold uppercase">Body Weight</label>
                    <input
                      type="number"
                      min="100"
                      max="900"
                      step="100"
                      value={editableTypography.bodyWeight}
                      onChange={(e) => {
                        const next = { ...editableTypography, bodyWeight: Number(e.target.value || 400) };
                        setEditableTypography(next);
                        persistThemeState(lockedTokens, editableColors, next, editableSpacing);
                      }}
                      className="h-8 border border-[#050505] bg-white px-2"
                    />
                    <label className="font-bold uppercase">Line Height</label>
                    <input
                      type="number"
                      min="1"
                      max="2"
                      step="0.05"
                      value={editableTypography.bodyLineHeight}
                      onChange={(e) => {
                        const next = { ...editableTypography, bodyLineHeight: Number(e.target.value || 1.5) };
                        setEditableTypography(next);
                        persistThemeState(lockedTokens, editableColors, next, editableSpacing);
                      }}
                      className="h-8 border border-[#050505] bg-white px-2"
                    />
                    <label className="font-bold uppercase">H1 Size</label>
                    <input
                      type="number"
                      min="20"
                      max="120"
                      value={editableTypography.h1Size}
                      onChange={(e) => {
                        const next = { ...editableTypography, h1Size: Number(e.target.value || 40) };
                        setEditableTypography(next);
                        persistThemeState(lockedTokens, editableColors, next, editableSpacing);
                      }}
                      className="h-8 border border-[#050505] bg-white px-2"
                    />
                  </div>
                </div>

                <div className="border border-[#050505] bg-[#f5f5f5] p-3" style={buildThemeVars()}>
                  <p className="text-xs font-bold uppercase">Live Type Specimens</p>
                  <p
                    className="mt-2"
                    style={{
                      fontFamily: "var(--font-family-base)",
                      fontSize: "var(--font-size-h1)",
                      lineHeight: "1.1",
                      color: "var(--color-text-primary)",
                    }}
                  >
                    Heading Sample
                  </p>
                  <p
                    className="mt-2"
                    style={{
                      fontFamily: "var(--font-family-base)",
                      fontSize: "var(--font-size-body)",
                      lineHeight: "var(--line-height-body)",
                      fontWeight: "var(--font-weight-body)",
                      color: "var(--color-text-secondary)",
                    }}
                  >
                    The quick brown fox jumps over the lazy dog.
                  </p>
                </div>
              </div>
            </div>
          )}

          {spacing && (
            <div className="neo-frame p-4">
              <p className="mb-3 text-lg font-black uppercase tracking-[0.12em]">Spacing Visualizer</p>
              <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                <div className="space-y-2 border border-[#050505] bg-[#f5f5f5] p-3">
                  {Object.entries(editableSpacing).map(([key, value]) => (
                    <div key={key}>
                      <div className="mb-1 flex items-center justify-between text-xs font-bold uppercase">
                        <span>{key}</span>
                        <span>{value}px</span>
                      </div>
                      <input
                        type="range"
                        min="0"
                        max="64"
                        step="4"
                        value={value}
                        onChange={(e) => {
                          const next = { ...editableSpacing, [key]: Number(e.target.value) };
                          setEditableSpacing(next);
                          persistThemeState(lockedTokens, editableColors, editableTypography, next);
                        }}
                        className="w-full"
                      />
                    </div>
                  ))}
                </div>

                <div className="border border-[#050505] bg-[#f5f5f5] p-3" style={buildThemeVars()}>
                  <p className="text-xs font-bold uppercase">Drag Feedback</p>
                  <div className="mt-2 border border-dashed border-[#52525b] p-(--spacing-lg)">
                    <div className="border border-[#050505] bg-white p-(--spacing-md)">
                      <div className="border border-[#050505] p-(--spacing-sm) text-xs">Spacing responds in 4px steps.</div>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          )}

          {colors && (
            <div className="neo-frame p-4" style={buildThemeVars()}>
              <p className="mb-3 text-lg font-black uppercase tracking-[0.12em]">Live Preview</p>
              <div className="mb-3 grid grid-cols-3 gap-2 md:hidden">
                {[
                  ["button", "Button"],
                  ["card", "Card"],
                  ["input", "Input"],
                ].map(([value, label]) => (
                  <button
                    key={value}
                    type="button"
                    onClick={() => setPreviewTab(value)}
                    className={`min-h-11 border border-[#050505] px-2 text-xs font-black uppercase ${previewTab === value ? "bg-[#ff3b30] text-[#050505]" : "bg-[#ebebeb] text-[#3f3f46]"}`}
                  >
                    {label}
                  </button>
                ))}
              </div>
              <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
                <div
                  className={`${previewTab === "button" ? "block" : "hidden"} border border-[#050505] p-4 md:block`}
                  style={{
                    backgroundColor: "var(--color-surface)",
                    color: "var(--color-text-primary)",
                    fontFamily: "var(--font-family-base)",
                  }}
                >
                  <p className="text-xs font-bold uppercase opacity-70">Primary Button</p>
                  <button
                    type="button"
                    className="mt-2 border px-3 py-2 text-sm font-bold"
                    style={{
                      backgroundColor: "var(--color-primary)",
                      color: "var(--color-primary-foreground)",
                      borderColor: "var(--color-primary)",
                      padding: "var(--spacing-sm) var(--spacing-md)",
                    }}
                  >
                    Try Action
                  </button>
                </div>

                <div
                  className={`${previewTab === "card" ? "block" : "hidden"} border border-[#050505] p-4 md:block`}
                  style={{
                    backgroundColor: "var(--color-surface-alt)",
                    color: "var(--color-text-primary)",
                    fontFamily: "var(--font-family-base)",
                  }}
                >
                  <p className="text-xs font-bold uppercase opacity-70">Card</p>
                  <p className="mt-2 text-sm">Live card preview updates instantly as tokens change.</p>
                </div>

                <div className={`${previewTab === "input" ? "block" : "hidden"} border border-[#050505] p-4 md:block`} style={{ backgroundColor: "var(--color-surface)", fontFamily: "var(--font-family-base)" }}>
                  <p className="text-xs font-bold uppercase opacity-70">Input States</p>
                  <input
                    readOnly
                    value="Focus state"
                    className="mt-2 w-full border px-2 py-2 text-sm"
                    style={{
                      borderColor: "var(--color-primary)",
                      color: "var(--color-text-primary)",
                      backgroundColor: "var(--color-surface)",
                    }}
                  />
                </div>
              </div>
            </div>
          )}

          {colors && (
            <div className="neo-frame p-4">
              <p className="mb-3 text-lg font-black uppercase tracking-[0.12em]">Semantic Colors</p>
              <div className="grid grid-cols-1 gap-2 text-sm sm:grid-cols-2">
                {Object.entries(colors)
                  .filter(([name]) => name !== "neutrals")
                  .map(([name, value]) => (
                    <div key={name} className="grid grid-cols-[1fr_auto_auto] items-center gap-3 border border-[#050505] bg-[#f5f5f5] px-3 py-2">
                      <span className="font-bold text-[#050505]">{prettyLabel(name)}</span>
                      <span className="inline-block h-4 w-4 border border-[#050505]" style={{ backgroundColor: tokenValue(value) || "transparent" }} />
                      <span className="font-mono text-xs">{tokenValue(value) || "n/a"}</span>
                    </div>
                  ))}
              </div>

              {colors.neutrals && (
                <div className="mt-4">
                  <p className="mb-2 font-bold uppercase">Neutrals</p>
                  <div className="grid grid-cols-1 gap-2 text-sm sm:grid-cols-3">
                    {Object.entries(colors.neutrals).map(([step, value]) => (
                      <div key={step} className="grid grid-cols-[auto_auto_1fr] items-center gap-3 border border-[#050505] bg-[#f5f5f5] px-3 py-2">
                        <span className="font-semibold">{step}</span>
                        <span className="inline-block h-4 w-4 border border-[#050505]" style={{ backgroundColor: tokenValue(value) || "transparent" }} />
                        <span className="justify-self-end font-mono text-xs">{tokenValue(value) || "n/a"}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

          {typography && (
            <div className="neo-frame p-4">
              <p className="mb-3 text-lg font-black uppercase tracking-[0.12em]">Typography</p>

              <div className="mb-4">
                <p className="mb-1 font-bold uppercase">Font Families</p>
                <ul className="space-y-1 text-sm">
                  {(typography.font_family || []).map((item, i) => (
                    <li key={i}>{tokenValue(item)}</li>
                  ))}
                </ul>
              </div>

              <div className="mb-4">
                <p className="mb-1 font-bold uppercase">Body Size</p>
                <p className="text-sm">{tokenValue(typography.body_size) || "Not detected"}</p>
              </div>

              <div>
                <p className="mb-1 font-bold uppercase">Type Scale</p>
                <ul className="space-y-2 sm:hidden">
                  {(typography.scale || []).map((item, i) => (
                    <li key={i} className="border border-[#050505] bg-[#f5f5f5] px-3 py-2 text-xs">
                      <p className="font-bold uppercase">{item.step}</p>
                      <p>Size: {tokenValue(item.size)}</p>
                      <p>Weight: {tokenValue(item.weight)}</p>
                      <p>Line Height: {tokenValue(item.line_height)}</p>
                      <p>Letter Spacing: {tokenValue(item.letter_spacing)}</p>
                    </li>
                  ))}
                </ul>
                <div className="hidden overflow-x-auto border border-[#050505] bg-[#f5f5f5] sm:block">
                  <div className="grid min-w-140 grid-cols-5 border-b border-[#050505] bg-[#ebebeb] px-3 py-2 text-[11px] font-bold uppercase tracking-[0.08em]">
                    <span>Step</span>
                    <span>Size</span>
                    <span>Weight</span>
                    <span>Line Height</span>
                    <span>Letter Spacing</span>
                  </div>
                  <ul className="divide-y divide-[#d4d4d8] text-sm">
                  {(typography.scale || []).map((item, i) => (
                    <li key={i} className="grid min-w-140 grid-cols-5 px-3 py-2">
                      <span className="font-semibold">{item.step}</span>
                      <span>{tokenValue(item.size)}</span>
                      <span>{tokenValue(item.weight)}</span>
                      <span>{tokenValue(item.line_height)}</span>
                      <span>{tokenValue(item.letter_spacing)}</span>
                    </li>
                  ))}
                  </ul>
                </div>
              </div>
            </div>
          )}

          {spacing && (
            <div className="neo-frame p-4">
              <p className="mb-3 text-lg font-black uppercase tracking-[0.12em]">Spacing</p>
              <div className="grid grid-cols-2 gap-2 text-sm sm:grid-cols-4 lg:grid-cols-7">
                {Object.entries(spacing).map(([name, value]) => (
                  <div key={name} className="border border-[#050505] bg-[#f5f5f5] p-2 text-center">
                    <p className="font-bold uppercase">{name}</p>
                    <p>{tokenValue(value)}</p>
                  </div>
                ))}
              </div>
            </div>
          )}

          {radii && (
            <div className="neo-frame p-4">
              <p className="mb-3 text-lg font-black uppercase tracking-[0.12em]">Radii</p>
              <div className="grid grid-cols-2 gap-2 text-sm sm:grid-cols-4">
                {Object.entries(radii).map(([name, value]) => (
                  <div key={name} className="border border-[#050505] bg-[#f5f5f5] p-3">
                    <p className="font-bold uppercase">{name}</p>
                    <p>{tokenValue(value)}</p>
                  </div>
                ))}
              </div>
            </div>
          )}

          {imagePalette && (
            <div className="neo-frame p-4">
              <p className="mb-3 text-lg font-black uppercase tracking-[0.12em]">Image Palette</p>
              <p className="mb-2 text-xs font-bold uppercase tracking-[0.08em] text-[#52525b]">
                Source: {meta?.image_palette_source || "dom-images"}
              </p>
              <div className="mb-3">
                <p className="mb-1 font-bold uppercase">Dominant</p>
                <div className="flex flex-wrap gap-2">
                  {(imagePalette.dominant || []).map((value, i) => (
                    <span key={i} className="flex items-center gap-2 border border-[#050505] bg-[#f5f5f5] px-2 py-1 text-xs font-semibold">
                      <span className="inline-block h-3 w-3 border border-[#050505]" style={{ backgroundColor: tokenValue(value) || "transparent" }} />
                      {tokenValue(value)}
                    </span>
                  ))}
                </div>
              </div>

              <div>
                <p className="mb-1 font-bold uppercase">Vibrant</p>
                <p className="text-sm flex items-center gap-2">
                  <span className="inline-block h-3 w-3 border border-[#050505]" style={{ backgroundColor: tokenValue(imagePalette.vibrant) || "transparent" }} />
                  {tokenValue(imagePalette.vibrant) || "n/a"}
                </p>
              </div>
            </div>
          )}

          {meta && (
            <div className="neo-frame p-4">
              <p className="mb-3 text-lg font-black uppercase tracking-[0.12em]">Design Meta</p>
              <div className="grid grid-cols-1 gap-2 text-sm sm:grid-cols-3">
                <p><span className="font-bold uppercase">Style:</span> {meta.style}</p>
                <p><span className="font-bold uppercase">Density:</span> {meta.density}</p>
                <p><span className="font-bold uppercase">Color Mode:</span> {meta.color_mode}</p>
              </div>
            </div>
          )}

          {components?.buttons && (
            <div className="neo-frame p-4">
              <p className="mb-3 text-lg font-black uppercase tracking-[0.12em]">Components: Buttons</p>
              <div className="space-y-4">
                {Object.entries(components.buttons)
                  .filter(([, btn]) => !!btn)
                  .map(([role, btn]) => (
                    <div key={role} className="border border-[#050505] bg-[#f5f5f5] p-3">
                      <p className="mb-2 text-sm font-bold uppercase">{role}</p>
                      <button
                        className="mb-2 border border-[#050505]"
                        style={{
                          backgroundColor: btn.background || "#222222",
                          color: btn.text || "#ffffff",
                          padding: btn.padding || "8px 14px",
                          borderRadius: btn.radius || "6px",
                          borderColor: btn.border_color || "transparent",
                          borderWidth: btn.border_width || "0px",
                          borderStyle: btn.border_style || "solid",
                          fontSize: btn.font_size || "14px",
                          fontWeight: btn.font_weight || "600",
                        }}
                      >
                        Sample Button
                      </button>
                      <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs sm:grid-cols-3">
                        {Object.entries({
                          background: btn.background || "n/a",
                          text: btn.text || "n/a",
                          border_color: btn.border_color || "n/a",
                          border_width: btn.border_width || "n/a",
                          border_style: btn.border_style || "n/a",
                          padding: btn.padding || "n/a",
                          radius: btn.radius || "n/a",
                          font_size: btn.font_size || "n/a",
                          font_weight: btn.font_weight || "n/a",
                        }).map(([k, v]) => (
                          <p key={k}><span className="font-bold">{prettyLabel(k)}:</span> {v}</p>
                        ))}
                      </div>
                    </div>
                  ))}
              </div>
            </div>
          )}

          {components?.input && (
            <div className="neo-frame p-4">
              <p className="mb-3 text-lg font-black uppercase tracking-[0.12em]">Components: Input</p>

              <div className="grid grid-cols-1 gap-3 text-sm sm:grid-cols-3">
                {["default", "focus", "error"].map((state) => (
                  <div key={state} className="border border-[#050505] bg-[#f5f5f5] p-3">
                    <p className="mb-2 font-bold uppercase">{state}</p>
                    <input
                      readOnly
                      value="Input"
                      style={{
                        backgroundColor: components.input.default?.background || "#ffffff",
                        borderColor:
                          state === "focus"
                            ? components.input.focus?.border_color || "#000000"
                            : state === "error"
                              ? components.input.error?.border_color || "#ce0026"
                              : components.input.default?.border_color || "#e0e0e0",
                        borderWidth: "1px",
                        borderStyle: "solid",
                        padding: components.input.default?.padding || "8px 12px",
                        width: "100%",
                      }}
                    />
                    <div className="mt-2 space-y-1 text-xs">
                      {Object.entries(components.input[state] || {}).map(([k, v]) => (
                        <p key={k}><span className="font-bold">{prettyLabel(k)}:</span> {String(v)}</p>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {components?.card && (
            <div className="neo-frame p-4">
              <p className="mb-3 text-lg font-black uppercase tracking-[0.12em]">Components: Card</p>
              <div
                className="border border-[#050505]"
                style={{
                  backgroundColor: components.card.background || "#ffffff",
                  borderRadius: components.card.radius || "12px",
                  padding: components.card.padding || "24px",
                }}
              >
                Card sample
              </div>
            </div>
          )}
          </div>
        </section>
      )}
      </section>
    </main>
  );
}