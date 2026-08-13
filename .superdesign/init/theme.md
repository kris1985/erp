# Compact token summary

- Framework: Vue 3, Element Plus and Vant; CSS is vanilla global CSS plus scoped Vue styles.
- Main mobile workspace palette: `--ws-primary` blue (used for active controls); background/elevated surfaces, ink, muted, line, danger, soft shadow and radius tokens are defined in `web/src/styles.css`.
- Legacy/root palette: text `#6b6375`, heading `#08060d`, white background, border `#e5e4e7`, violet accent `#aa3bff`; dark mode provides `#16171d` background and `#c084fc` accent.
- Font stack: system UI / Segoe UI / Roboto; display text via `--ws-font-display`.
- Product patterns: light mobile cards, compact numeric metrics, rounded 10–16px surfaces; Element Plus dense desktop admin panels.

# Raw source locations

- `web/src/styles.css` (512 lines): primary workspace tokens and mobile component rules.
- `web/src/admin.css` (801 lines): desktop ERP admin theme.
- `web/src/style.css` (296 lines): Vite base / legacy global styles.
- No Tailwind configuration is present.
