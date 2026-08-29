/** Rootlize landing-page content. Internal `window.CAPIXE` key is unchanged. */
window.CAPIXE = {
  brand: {
    name: "Rootlize",
    tagline: "Your Local Workspace.",
    description: "Find, organize, and work with the images on your PC — without moving them to the cloud.",
  },
  version: {
    channel: "Prototype Preview",
    number: "0.1.0-preview",
    get label() { return "Version " + this.number; },
    platform: "Windows",
  },
  downloadBadges: ["Windows", "Free", "Sign-in required", "Local-first"],
  urls: {
    github: "https://github.com/p1rworks24-ops/Rootlize",
    releases: "https://github.com/p1rworks24-ops/Rootlize/releases",
    releasesApi: "https://api.github.com/repos/p1rworks24-ops/Rootlize/releases?per_page=10",
    // Planned GitHub Release asset. Do not use as a live href until this exact file exists.
    downloadAsset: "Rootlize-v0.1.0-preview-win64.zip",
    downloadTag: "v0.1.0-preview",
    download:
      "https://github.com/p1rworks24-ops/Rootlize/releases/download/v0.1.0-preview/Rootlize-v0.1.0-preview-win64.zip",
    license: "https://github.com/p1rworks24-ops/Rootlize/blob/master/LICENSE",
    issues: "https://github.com/p1rworks24-ops/Rootlize/issues",
    bugReport: "https://github.com/p1rworks24-ops/Rootlize/issues/new?template=bug_report.yml",
    featureRequest: "https://github.com/p1rworks24-ops/Rootlize/issues/new?template=feature_request.yml",
    contact: "https://github.com/p1rworks24-ops/Rootlize/issues/new?template=feature_request.yml",
  },
  screenshots: [
    {
      src: "assets/screenshots/images.png",
      alt: "Rootlize Images workspace with brand header and Basic Search",
      caption: "Images — Rootlize header, then Basic Search by filename, tags, or text in images",
      slot: "images",
    },
    {
      src: "assets/screenshots/meaning-search.png",
      alt: "Rootlize Meaning Search for images by what they show",
      caption: "Meaning Search — find images by what they show, with the model bundled in the app",
      slot: "meaning-search",
    },
    {
      src: "assets/screenshots/ask-ai.png",
      alt: "Rootlize Ask AI panel beside the Images workspace",
      caption: "Ask AI — describe find and organize work in your own words",
      slot: "ask-ai",
    },
    {
      src: "assets/screenshots/automation.png",
      alt: "Rootlize Automation page for saved workflows",
      caption: "Automation — save a repeated find-and-organize flow and run it again",
      slot: "automation",
    },
    {
      src: "assets/screenshots/account.png",
      alt: "Rootlize Account page showing the Prototype plan",
      caption: "Account — Prototype plan and local-first use after sign-in",
      slot: "account",
    },
  ],
  faq: [
    {
      q: "Does Rootlize upload my image library?",
      a: "No. Rootlize is local-first: it works with folders already on your PC and does not move the image library to a Rootlize cloud. Settings and the local search index stay on this PC.",
    },
    {
      q: "What runs locally, and what needs the internet?",
      a: "Basic Search, OCR, and bundled Meaning Search run on this PC. You do need to sign in to use the Prototype. Account features and Ask AI need the internet. Ask AI uses an external AI service after you agree, and may send image contents for analysis.",
    },
    {
      q: "Do I need to set up a Meaning Search model?",
      a: "No. Meaning Search ships with the app. There is no separate model download or extra setup step.",
    },
    {
      q: "Is Rootlize free?",
      a: "The current Prototype Preview is free to download and try. There is no subscription. You do need to sign in to use the preview.",
    },
    {
      q: "Do I need an account?",
      a: "Yes. The Prototype opens on a sign-in screen. Sign in with Google, GitHub, or email to continue. Sign-in is for your Rootlize account — it does not upload your image files.",
    },
    {
      q: "Which operating systems are supported?",
      a: "Windows only (Windows 10 / Windows 11, 64-bit). macOS and Linux are not supported in this preview.",
    },
    {
      q: "Do I need to install Python?",
      a: "No. The Release ZIP is a portable Windows build. Keep Rootlize.exe together with the _internal folder and run Rootlize.exe.",
    },
  ],
};
