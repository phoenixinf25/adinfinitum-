# Vendored third-party code (MIT)

Copied unmodified from npm so the page works offline, with no CDN and no build step.

| Folder | Package | Version | Used for | Source |
|---|---|---|---|---|
| `openui/` | `@openuidev/browser-bundle` | 0.2.2 | The "Charts" tab: OpenUI's React renderer and chart components (area, line, bar, pie, radar, radial, scatter), including their built-in animation. Exposes `window.__OpenUI`. | https://github.com/thesysdev/openui |
| `number-flow/` | `number-flow` | 0.6.2 | Animated number transitions (the `<number-flow>` custom element) in the top bar, tables and tiles. | https://github.com/barvian/number-flow |

Both are MIT licensed; the licence files are next to the code.

`number-flow/esm-env.mjs` is a one-line stand-in for the `esm-env` package that NumberFlow imports by bare name (its `BROWSER` flag is always `true` in a browser). It is wired up with an import map in `index.html`.

| `fonts/` | Instrument Sans (variable) and JetBrains Mono (variable), Latin subset, from `@fontsource-variable/*` 5.3.0 | | Instrument Sans for all text, a free lookalike for Anthropic's licensed Styrene. JetBrains Mono only for numbers. Both SIL OFL 1.1 (licences next to the files). | https://github.com/Instrument/instrument-sans, https://github.com/JetBrains/JetBrainsMono |
