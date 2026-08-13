---
version: "superdesign-alpha"
name: "Foundry Amber"
description: "Dark-mode-default industrial console system: near-black surfaces, a single rationed amber accent, tight geometric sans, and a photographic factory-floor hero dimmed to near-monochrome."
colors:
  background: "#0A0C10"
  surface: "#111722"
  surface-elevated: "rgba(22, 27, 40, 0.4)"
  text-primary: "#E7EBEF"
  text-secondary: "#8A96A8"
  accent: "#F6AE31"
  border: "#2D3643"
  footer-bg: "#0B0E14"
typography:
  display-lg:
    fontFamily: "Space Grotesk"
    fontSize: "16px"
    fontWeight: 400
    lineHeight: "1.5"
  headline-md:
    fontFamily: "Space Grotesk"
    fontSize: "36px"
    fontWeight: 700
    lineHeight: "1.25"
    letterSpacing: "-0.9px"
  body-md:
    fontFamily: "Space Grotesk"
    fontSize: "16px"
    fontWeight: 400
    lineHeight: "1.5"
  label-md:
    fontFamily: "Space Grotesk"
    fontSize: "14px"
    fontWeight: 600
    lineHeight: "1.43"
  body-char:
    fontFamily: "Space Grotesk"
    fontSize: "14px"
    fontWeight: 400
    lineHeight: "1.5"
  accent-mono:
    fontFamily: "Source Code Pro"
    role: "tabular/data-panel figures inside product screenshot"
spacing:
  base: "8px"
  gap: "40px"
  section-padding: "112px"
rounded:
  control: "6px"
  card: "6px"
  pill: "9999px"
  sharp: "4px"
components:
  button-hero-primary:
    background: "#F6AE31"
    text-color: "#0F1724"
    radius: "6px"
    height: "52px"
    padding: "14px 32px"
    shadow: "rgba(0,0,0,0) 0px 0px 0px 0px, rgba(0,0,0,0) 0px 0px 0px 0px, rgba(0,0,0,0) 0px 0px 0px 0px, rgba(0,0,0,0) 0px 0px 0px 0px, rgba(0,0,0,0.02) 0px 2px 12px 0px, rgba(0,0,0,0.02) 0px 4px 6px -1px"
  button-nav-cta:
    background: "#F6AE31"
    text-color: "#0F1724"
    radius: "6px"
    height: "32px"
    padding: "0px 12px"
    border: "1px solid rgb(45, 54, 67)"
    shadow: "rgba(0,0,0,0) 0px 0px 0px 0px, rgba(0,0,0,0) 0px 0px 0px 0px, rgba(0,0,0,0) 0px 0px 0px 0px, rgba(0,0,0,0) 0px 0px 0px 0px, rgba(0,0,0,0.02) 0px 2px 12px 0px, rgba(0,0,0,0.02) 0px 2px 4px -1px"
  button-ghost-nav-link:
    background: "transparent"
    text-color: "#E7EBEF"
    radius: "6px"
    height: "83px"
    padding: "8px 4px"
  button-ghost-utility:
    background: "transparent"
    text-color: "#E7EBEF"
    radius: "6px"
    height: "42px"
    padding: "10px 14px"
    border: "1px solid rgba(0,0,0,0)"
  card-full-panel:
    background: "transparent"
    radius: "0px"
    padding: "112px 0px"
  card-expandable-row:
    background: "transparent"
    radius: "0px"
    padding: "0px"
  card-media-right:
    background: "transparent"
    radius: "0px"
    padding: "0px"
  card-glass-icon-sm:
    background: "rgba(22, 27, 40, 0.4)"
    radius: "6px"
    padding: "16px"
  card-glass-body:
    background: "rgba(20, 27, 40, 0.15)"
    radius: "6px"
    padding: "24px"
  card-glass-icon-md:
    background: "rgba(24, 28, 40, 0.25)"
    radius: "6px"
    padding: "16px"
  card-glass-heading-icon:
    background: "rgba(24, 28, 40, 0.25)"
    radius: "6px"
    padding: "24px"
  navbar:
    background: "transparent"
    backdrop-filter: "blur(12px)"
    radius-tl: "0px"
    radius-tr: "0px"
    radius-br: "0px"
    radius-bl: "0px"
    height: "72px"
---
# Foundry Amber
Source: http://112.74.191.133/

## Overview
A dark-mode-default industrial console aesthetic: near-black slate surfaces (#0A0C10, #111722), a tightly-tracked geometric sans (Space Grotesk) carrying every weight of the hierarchy, and a single amber (#F6AE31) reserved for calls to action and small labels. The system reads as an operations dashboard skinned as a marketing page — flat rectangular panels, zero-radius section dividers, hairline borders (#2D3643) instead of shadows for most separation, and one real product screenshot (a dark dashboard mockup) doing the visual heavy lifting instead of illustration or 3D.

## Composition
The first screen is hero-led: a dimmed factory photograph fills the full viewport behind centered headline text, with a bold two-line statement, a supporting paragraph, and one solid amber button — then a floating "browser-style" dashboard screenshot anchored center-low, overlapping into the next section. Below the fold the page runs as a strict vertical stack of full-bleed sections at ~112px padding: a before/after comparison table, a stat/callout with three icon-label triples, an AI-agent feature spread with two screenshots and a text pairing, a three-card boundary/scope grid, a searchable two-column FAQ (left index, right accordion), a five-step numbered process rail, and a closing CTA band over a second dimmed photograph, ending in a four-column footer. Density is high in the FAQ and comparison sections (long text rows, thin dividers) and deliberately sparse in the hero and CTA bands — this rejects a uniform whitespace rhythm in favor of alternating tight/loose bands that mimic a documentation product, not a soft SaaS lander.

## Colors
Background is near-black across ~79% of pixels (#181818 field, backed by the declared #0A0C10 / #111722 surface pair) — this is a genuinely dark system, not a light system with a dark hero. A cool navy-black (#001818-adjacent, ~9%) tints the photographic hero zones. White (#FFFFFF, ~3%) and off-white (#F0F0F0, ~2%) appear only inside the embedded dashboard screenshot's light UI chrome, never as page background. Amber #F6AE31 is the only saturated hue in the entire system and is rationed hard: hero CTA, nav CTA, eyebrow labels ("产品价值"-style small caps), numeral badges in the process rail, and link-arrow accents — never fills, never backgrounds. Borders (#2D3643, #2E3644) and secondary text (#8A96A8) carry all remaining structure. Red swatches (#F54A45 family) exist in token declarations but are not visible on-page — reserved for a danger state not shown in these screenshots.

## Typography
Space Grotesk is the sole family across every weight: headline-md at 36px/700 with tight -0.9px tracking drives every section title; body copy sits at 16px/400 (display-lg token) for intro paragraphs and drops to a denser 14px/400 body-char mode inside comparison rows and FAQ answers; label-md at 14px/600 marks eyebrows and small UI chips. A monospace (Source Code Pro) appears only inside the embedded dashboard screenshot for tabular figures — a signature but strictly contained accent, never used in real page type. Hierarchy is built through size and tracking, not color: only the eyebrow labels break into amber.

## Layout
Content is capped at a 1152px max-width, centered. The comparison table and FAQ run as two explicit 12-column-derived splits — one at roughly 40/57 (label vs. detail), another sidebar/detail FAQ layout at 31/65. The process rail is a flat 5-up row of equal-width numbered cards linked by connecting arrows. The scope/boundary section is a strict 3-up card row. Gap is consistently 40px between grid siblings; section padding runs 112px top/bottom, giving each band generous vertical breathing room despite the otherwise dense internal typography. Corner radii are almost binary: 0px for structural panels and dividers, 6px for every interactive control and glass card — no large card radius exists anywhere in this system.

## Components
- **Navbar**: edge-to-edge, full 100% viewport width, 0/0/0/0 corner radii (square, not inset, not capsule), 72px tall, sticky, transparent background with `backdrop-filter: blur(12px)`. Carries a small square logomark + two-line wordmark/tagline at left, 5 text nav items center, one amber CTA at right (#F6AE31 fill, #0F1724 text, 6px radius, 32px height, 1px solid rgb(45,54,67) border).
- **Hero primary button**: the solid amber pill-adjacent rectangle beneath the headline — #F6AE31 fill, #0F1724 text, 6px radius (slightly-rounded, not pill), 52px height, 14px/32px padding, near-invisible ambient shadow. This is the single most emphasized control on the first screen; the navbar's amber button is a smaller nav utility, not this primary.
- **Ghost nav-link buttons**: transparent fill, #E7EBEF text, 6px radius, appearing as the horizontal section-jump links beneath the navbar (83px tall hit targets) and as filter/tab utilities mid-page (42px tall, 10px/14px padding, invisible border) — sharp-cornered functional labels, no fill state shown at rest.
- **Comparison table rows** (full-panel card family): transparent background, 0px radius, 112px vertical padding per row, full-width; each row pairs a muted "before" phrase on the left with an arrow icon and an amber-adjacent "now" phrase and short body sentence on the right — eight stacked full-width rows, no card chrome at all.
- **Expandable FAQ rows**: transparent, 0px radius, arranged as eight ~94%-width rows inside the right-hand accordion panel; each row is a heading question + chevron icon, expanding to reveal body-text answers; paired with a left sidebar list of category labels (one active/outlined state visible).
- **Feature/media split cards** (media-right family): transparent, 0px radius, four full-width rows alternating a heading+body text block with a right-aligned screenshot or icon graphic — this is the AI-agent section's two-screenshot showcase.
- **Scope/boundary cards** (×3, one row): background rgba(24,28,40,0.25)-class glass, 6px radius, 24px padding; each carries a small icon top-left, a small status chip top-right ("规划中" style label), a short heading, and one line of body text — describes what is explicitly out of scope.
- **Small glass icon chips** (×5, near page end / ×4 mid-page): rgba(22,27,40,0.4) or rgba(24,28,40,0.25) fill, 6px radius, 16px padding, icon-only or icon+label — used as compact metadata tags beside process steps and inside the dashboard screenshot's stat tiles.
- **Numbered process rail** (5-up row): each step is a small circular amber-outlined numeral badge above an icon, bold label, and one-line caption; steps connect via thin horizontal arrow glyphs; row sits above a second hero-style CTA button of the same primary spec.
- **CTA band**: full-bleed section over a second dimmed factory photograph, centered eyebrow label, two-tone headline (white + amber clause), one-line supporting text — no button repeated here, it defers to the primary button already placed above it.
- **Footer**: solid #0B0E14 background, 0px radius, four-column layout — logomark/tagline block, two address/phone location blocks, and an 8-link product index — separated from the CTA band by a hairline border only.

## Graphics & Effects
Two radial washes are layered into the mid-page dark sections, each covering roughly a quarter of total page height: `radial-gradient(900px 480px at 100% 0%, rgba(246, 174, 49, 0.07), rgba(0, 0, 0, 0) 55%)` (amber glow, top-right corner) and `radial-gradient(700px 420px at 0% 100%, rgba(46, 70, 107, 0.18), rgba(0, 0, 0, 0) 50%)` (cool navy glow, bottom-left corner) — both are corner-anchored accents on otherwise flat dark panels, never full-frame color. A base panel gradient `linear-gradient(rgb(17, 23, 34) 0%, rgb(13, 18, 28) 100%)` gives sections a barely-perceptible top-to-bottom darkening. The hero and closing CTA photographs each carry a directional scrim, `linear-gradient(to right, rgb(7, 11, 18) 0%, lab(2.92532 -0.169508 -3.77853 / 0.88) 50%, lab(2.92532 -0.169508 -3.77853 / 0.25) 100%)`, darkening the photo from left to right so text stays legible against factory-floor imagery — this scrim covers only the hero/CTA photo elements (~10% of total page height combined), not the whole page. A secondary vertical scrim `linear-gradient(lab(2.92532 -0.169508 -3.77853 / 0.5) 0%, rgba(0,0,0,0) 50%, rgb(7,11,18) 100%)` blends photo into surrounding flat sections top and bottom. The dashboard screenshot itself carries its own subtle top-left highlight scrim (`oklab(0.999994 ... / 0.04)`) and corner amber glow, simulating screen glare. Buttons carry near-invisible ambient shadows (`rgba(0,0,0,0.02)` blurs) rather than hard drop shadows — elevation is implied by border and glass translucency, not by strong shadow.

## Motion
Interactive color/border/fill transitions run at `0.15s cubic-bezier(0.4, 0, 0.2, 1)` — fast, snappy state changes on hover/focus. Transform-based motion (scale, translate, rotate) runs slightly slower at `0.2s cubic-bezier(0.4, 0, 0.2, 1)`, giving buttons and icons a crisp settle rather than a bounce. A slower `0.5s cubic-bezier(0.4, 0, 0.2, 1)` governs larger compound state changes (accordion expand/collapse via accordion-down/accordion-up keyframes). Spin and pulse keyframes exist for loading/status indicators inside the dashboard screenshot. All motion is utilitarian and quick — no spring-overshoot, no parallax scroll — consistent with the console/dashboard character rather than a marketing-forward system.

## Guardrails
- Never fill large surfaces with amber — it is a control/label/glow color only, rationed to under a few percent of any view.
- Never round structural section panels or table rows beyond 0px; reserve 6px exclusively for buttons and glass cards.
- Never replace the corner-anchored radial glows with full-screen gradients — they are small, corner-positioned washes at low opacity.
- Never brighten the base page background above near-black; all elevation comes from translucent glass fills and hairline borders, not lighter flat surfaces.
- Never give the hero photograph a saturated color treatment — it stays scrim-darkened and near-monochrome so the amber CTA remains the only vivid element on that screen.
- Never substitute the nav CTA's 32px-height spec for the hero primary button's 52px spec, or vice versa — they are distinct variants with distinct roles.