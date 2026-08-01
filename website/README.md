# Capixe website

Official marketing landing page for Capixe (static HTML/CSS/JS).

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
- Screenshot gallery (`screenshots` array)

## Screenshots gallery

The gallery is **data-driven**. To add more shots:

1. Add image files under `assets/screenshots/`.
2. Append objects to `screenshots` in `js/content.js`:

```js
{
  src: "assets/screenshots/your-shot.png",
  alt: "…",
  caption: "…",
  slot: "unique-id",
}
```

The gallery uses two columns on larger screens and one column on mobile. `main.js` renders the list into `#screenshot-gallery` and provides the lightbox behavior.

Hero search view: `images-search.png`

Gallery order: `images.png`, `organize.png`, `home.png`, `tags.png`, `about.png`

Brand icon: `assets/brand/app-icon.png` (also used as favicon)

## Future pages

Add siblings next to `index.html` without refactoring the app:

- `changelog.html`
- `pricing.html`
- `docs/` (documentation)

Share `css/styles.css` and `js/content.js` where useful.
