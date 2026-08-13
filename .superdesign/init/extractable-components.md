# Extractable components

## MainLayout
- Source: `web/src/layouts/MainLayout.vue`
- Category: layout
- Description: authenticated mobile application shell with role-dependent navigation.
- Extractable props: `activeItem`, `actor`, `navTitle`, `showScan`.
- Hardcoded: navigation labels, Vant icons and layout styles.

## AdminLayout
- Source: `web/src/layouts/AdminLayout.vue`
- Category: layout
- Description: desktop ERP navigation and content shell.
- Extractable props: `activeItem`, `collapsed`, `userName`.
- Hardcoded: menu labels, admin shell styling.

## ProgressRing
- Source: `web/src/components/ProgressRing.vue`
- Category: basic
- Description: compact colored progress indicator.
- Extractable props: `value`, `color`.
- Hardcoded: ring geometry.
