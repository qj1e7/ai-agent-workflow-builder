---
status: proposed
---

# The Portal uses Atkinson Hyperlegible Next, served from our own origin

The team lead approved the Tracker template for the run view, and its type is Atkinson Hyperlegible Next. The typeface was drawn for low-vision readers, which suits support staff who read the run view at a glance. We replace the `@fontsource-variable/instrument-sans` package with `@fontsource-variable/atkinson-hyperlegible-next` (same supplier, same version line, SIL Open Font License). Vite bundles the font file, so it is served from the Portal's own origin and the Content Security Policy (`font-src 'self'`) stays as it is.

## Considered options

- **Keep Instrument Sans.** No new package, but the Portal would not look like the template the lead approved.
- **Load the font from Google Fonts, as the template does.** The CSP blocks other origins, and a DevNet host may not reach Google at all.
