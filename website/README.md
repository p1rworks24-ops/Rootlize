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
- Version (`channel` + `number` → shown as Prototype Preview / Version x.x.x)
- Download badges
- FAQ items
- GitHub / Releases / Issues URLs
- Download asset wiring (`urls.downloadAsset`, `urls.downloadTag`, `urls.download`)
- Hero carousel slides (`screenshots` array)

Do not point Download CTAs at `urls.download` until GitHub has that exact ZIP. `js/main.js` enables Download Preview only when Releases API returns `Rootlize-v0.1.0-preview-win64.zip`. Until then the buttons stay on `#download`. After the Rootlize GitHub Release is published, no extra LP edit is required if that filename is attached. If the tag cannot be `v0.1.0-preview`, keep the filename and let the API match it, or update `urls.downloadAsset`.

## Hero carousel

The product showcase is **data-driven**. `main.js` renders `screenshots` from `js/content.js` into `#hero-carousel` (auto-advance, arrows, dots, swipe, lightbox). Honor `prefers-reduced-motion`.

Keep all slides the same pixel size and aspect ratio so the frame does not letterbox. Replace files in place — do not change `js/content.js` keys.

Recommended drop-in assets:

- 3 distinct product shots is enough (the carousel accepts any length)
- `1600 × 930` PNG (aspect `1600 / 930`)
- Same crop / window chrome on every slide
- Filenames: `images.png`, `meaning-search.png`, `ask-ai.png`, `automation.png`, `account.png`

The landing page presents Rootlize as a local workspace (Find → Narrow → Act → Automate). Desktop implementation Source of Truth remains `.ai/SPEC.md`.

Brand icon: `assets/brand/app-icon.png` (512px, transparent). Tab icon: `assets/brand/favicon.png`.

Public legal pages:

- [Privacy Policy](privacy/index.html) — `https://rootlize.com/privacy`
- [Terms](terms/index.html) — `https://rootlize.com/terms`

## Future pages

Add siblings next to `index.html` without refactoring the app:

- `changelog.html`
- `pricing.html`
- `docs/` (documentation)

Share `css/styles.css` and `js/content.js` where useful.
