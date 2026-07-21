# Static Site Implementation Plan

**Goal:** Publish a GitHub Pages-safe product overview and local interactive demo.

**Files:** `site/index.html`, `site/assets/styles.css`, `site/assets/app.js`, `site/assets/demo-data.js`, `.github/workflows/pages.yml`.

1. Create a no-build static page with product overview and demo workbench.
2. Store only fictional scenarios and results in `demo-data.js`.
3. Render normal, incomplete, no-data and failure states in browser JavaScript.
4. Publish only `site/` through a Pages workflow.
5. Verify the page locally and run project tests.
