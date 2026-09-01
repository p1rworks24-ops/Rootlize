# Rootlize website

Official marketing landing page for Rootlize (static HTML/CSS/JS).

Not part of the desktop app runtime. No npm build step.

## Open locally

Open `index.html` in a browser, or serve the folder:

```text
python -m http.server 8080 --directory website
```

Then visit `http://localhost:8080`.

## Edit copy and URLs

Edit [`js/content.js`](js/content.js):

- Brand name / tagline / description
- Version (`channel` + `number` → shown as Prototype Preview / v0.1.0-preview)
- Download badges
- FAQ items
- GitHub / Releases / Issues URLs
- Download asset wiring (`urls.downloadAsset`, `urls.downloadTag`, `urls.download`)
- Hero carousel slides (`screenshots` array)

The published Prototype ZIP is `Rootlize-v0.1.0-preview-win64.zip` on GitHub Release `v0.1.0-preview.1`. Download CTAs use `urls.download` immediately, then `js/main.js` confirms the same filename via the Releases API. If the live asset name changes, update `urls.downloadAsset` and `urls.download`.

The landing page presents Rootlize as a local workspace (Find → Organize → Automate). Desktop implementation Source of Truth remains `.ai/SPEC.md`.

## Hero carousel

The product showcase is **data-driven**. `main.js` renders `screenshots` from `js/content.js` into `#hero-carousel` (auto-advance, arrows, dots, swipe, lightbox). Honor `prefers-reduced-motion`.

Keep all slides the same pixel size and aspect ratio so the frame does not letterbox. Replace files in place — do not change `js/content.js` keys.

Recommended drop-in assets:

- 3 distinct product shots is enough (the carousel accepts any length)
- `1600 × 930` PNG (aspect `1600 / 930`)
- Same crop / window chrome on every slide
- Filenames: `images.png`, `meaning-search.png`, `ask-ai.png`, `automation.png`, `account.png`

Brand icon: `assets/brand/app-icon.png` (512px, transparent). Tab icon: `assets/brand/favicon.png`.

Public legal pages:

- [Privacy Policy](privacy/index.html) — `https://rootlize.com/privacy`
- [Terms](terms/index.html) — `https://rootlize.com/terms`

## Landing-page analytics

The landing page records `lp_visit`, `page_view`, and `download_click` to Supabase. It does not send IP addresses or a device fingerprint.

Operator opt-out for this browser (not shown to visitors):

- `http://localhost:8080/?analytics=off` or `https://rootlize.com/?analytics=off`
- Resume with `?analytics=on`
- Console: `__rootlizeAnalytics.optOut()`, `.optIn()`, `.status()`

The stored flag is `localStorage.rootlize_analytics_opt_out = true`.

## Operator admin

`https://rootlize.com/admin/` (local: `http://localhost:8080/admin/`). Sign in with a Rootlize account that is listed in `public.admin_users`. Ordinary users cannot load analytics data. See `supabase/README.md`.

## Future pages

Add siblings next to `index.html` without refactoring the app:

- `changelog.html`
- `pricing.html`
- `docs/` (documentation)

Share `css/styles.css` and `js/content.js` where useful.
