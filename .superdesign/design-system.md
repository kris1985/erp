# 铁玉兰管家官网 — 优化设计系统

## Source and intent

This is an **inspired-by / continuity-first** system derived from the current live site. Preserve the industrial, credible, operations-first character; improve hierarchy, scanning and demo conversion without turning it into a generic bright SaaS page.

## Non-negotiable visual DNA

- Near-black base `#0A0C10`, panels `#111722`, border `#2D3643`.
- Text `#E7EBEF`, supporting copy `#8A96A8`; single restrained amber `#F6AE31` for CTA, active state, labels and decision signals.
- Square structural geometry; only controls and small glass cards use 6px radius.
- Geometric sans: Space Grotesk; Chinese fallback `PingFang SC`, `Microsoft YaHei`, sans-serif. Use a mono face only inside product data/screenshot modules.
- Retain real factory photography and real product UI screenshots. Do not introduce illustrations, neon gradients, violet, pill-heavy components or consumer-app imagery.

## Improve, do not replace

1. Hero: make value proposition and one CTA immediately legible; show the real dashboard at usable scale and add a compact proof strip.
2. Narrative: collapse repetitive “what we do” explanations into a clear three-stage story: risk visible → decision confirmed → execution traceable.
3. Proof: surface three concrete, measurable claims/cards after hero (e.g. 缺料、交期、计件) before deep feature detail.
4. Feature explorer: retain the production-closure workflow, but use fewer words, bigger screenshots and an obvious selected state.
5. Conversion: repeat one primary demo CTA after proof and at the close; include a low-friction contact promise such as “15 分钟看一条主链路”.
6. Mobile: never hide the primary CTA or product dashboard completely. Use a smaller in-flow screen mock rather than a giant background visual that consumes the first screen.

## Component rules

- Desktop content width: 1152px, sections 96–112px vertical; mobile 24px horizontal padding with 56–72px section spacing.
- Primary button: amber, 52px high, 6px radius; secondary button is border-only.
- Proof cards: dark translucent surface, 1px border, 6px radius, 20–24px padding; no floating oversized shadows.
- H2: 36px desktop / 28px mobile, 700; body: 16px / 15px, line-height 1.6.
- Use amber as a sparse action color only; do not fill large areas or color full headings.

## Accessibility

- Increase long-body text contrast and keep default body at least 15–16px.
- Use visible focus rings, labelled icon-only controls, keyboard-operable tabs/accordions and at least 44px mobile touch targets.
- Respect `prefers-reduced-motion` and avoid autoplay-dependent messaging.
