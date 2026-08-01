/**
 * Capixe landing page content — edit URLs, version, and copy here.
 * Loaded before main.js; HTML data-* keys are filled at runtime.
 *
 * Screenshots: append objects to `screenshots` to grow the gallery (6+ supported).
 * Each item needs: src, alt, caption, slot (unique id). Optional: placeholder: true
 */
window.CAPIXE = {
  brand: {
    name: "Capixe",
    tagline: "Find the screenshot you need. Right now.",
    description:
      "Stop digging through folders for an image you know you saved. Capixe gives every capture a searchable home, so you can recover the right information without breaking your flow.",
  },
  version: {
    /** Shown as the channel line, e.g. Prototype Preview */
    channel: "Prototype Preview",
    /** Semver-style value without a leading "v" */
    number: "0.1.0-preview",
    /** Full line: Version 0.1.0-preview */
    get label() {
      return "Version " + this.number;
    },
    platform: "Windows",
  },
  downloadBadges: [
    "Windows",
    "Free",
    "No account required",
    "Local-first",
  ],
  urls: {
    github: "https://github.com/p1rworks24-ops/Capixe",
    releases: "https://github.com/p1rworks24-ops/Capixe/releases",
    download: "https://github.com/p1rworks24-ops/Capixe/releases",
    license: "https://github.com/p1rworks24-ops/Capixe/blob/master/LICENSE",
    issues: "https://github.com/p1rworks24-ops/Capixe/issues",
    bugReport:
      "https://github.com/p1rworks24-ops/Capixe/issues/new?template=bug_report.yml",
    featureRequest:
      "https://github.com/p1rworks24-ops/Capixe/issues/new?template=feature_request.yml",
    contact:
      "https://github.com/p1rworks24-ops/Capixe/issues/new?template=feature_request.yml",
  },
  /**
   * Gallery is data-driven. Add more entries (and image files) to expand past 6.
   * CSS uses auto-fit grid — no layout change required when the list grows.
   * Prefer full-window PNGs; CSS uses object-fit: contain (no cropping).
   */
  screenshots: [
    {
      src: "assets/screenshots/images.png",
      alt: "Capixe Images — browse screenshots grouped by tag with search",
      caption: "Images — find the right screenshot instantly",
      slot: "images",
    },
    {
      src: "assets/screenshots/organize.png",
      alt: "Capixe Organize — bulk tags and rename on a screenshot grid",
      caption: "Organize — update entire sets in a few clicks",
      slot: "organize",
    },
    {
      src: "assets/screenshots/home.png",
      alt: "Capixe Home — library overview, root folder, and capture bar",
      caption: "Home — see your whole library at a glance",
      slot: "home",
    },
    {
      src: "assets/screenshots/tags.png",
      alt: "Capixe Tags — create and manage tags for your library",
      caption: "Tags — organize images using words you remember",
      slot: "tags",
    },
    {
      src: "assets/screenshots/about.png",
      alt: "Capixe About — brand, version, repository and feedback links",
      caption: "About — check version details and share feedback",
      slot: "about",
    },
  ],
  faq: [
    {
      q: "Is my data sent to the cloud?",
      a: "No. Capixe is local-first. Screenshots, settings, and tags stay on your PC. Capixe does not upload your images to a Capixe cloud service.",
    },
    {
      q: "Does Capixe work offline?",
      a: "Yes. After you download the app, capture, browsing, tags, and organize tools work without an internet connection.",
    },
    {
      q: "Is Capixe free?",
      a: "The current Prototype Preview is free to download and try. There is no account and no subscription required for this preview.",
    },
    {
      q: "Which operating systems are supported?",
      a: "Windows only (Windows 10 / Windows 11, 64-bit). macOS and Linux are not supported in this preview.",
    },
    {
      q: "Do I need to install Python?",
      a: "No. The Release ZIP is a portable Windows build. Keep Capixe.exe together with the _internal folder and run Capixe.exe.",
    },
  ],
};
