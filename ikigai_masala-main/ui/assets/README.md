# Brand assets

Drop the SmartQ logo here to have it appear in the app (sidebar, editor
header, and browser-tab favicon). The app looks for these filenames, in order:

1. `smartq_logo.svg`  — preferred for the sidebar / editor header (crisp at any size)
2. `smartq_logo.png`  — used for the browser-tab **favicon** (add a PNG for the tab icon)

Recommended: add **both** `smartq_logo.svg` and `smartq_logo.png`.
- SVG: any size (it's inlined as a data URI).
- PNG: ~256×256, transparent background, for the favicon.

If neither file is present the app falls back to its default emoji mark — so
nothing breaks while the asset is missing.
