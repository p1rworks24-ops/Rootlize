/** Capixe landing-page content. */
window.CAPIXE = {
  brand: {
    name: "Capixe",
    tagline: "Find the screenshot you need. Right now.",
    description: "Stop digging through folders for an image you know you saved. Capixe gives every capture a searchable home, so you can recover the right information without breaking your flow.",
  },
  version: {
    channel: "Prototype Preview",
    number: "0.1.0-preview",
    get label() { return "Version " + this.number; },
    platform: "Windows",
  },
  downloadBadges: ["Windows", "Free", "No account required", "Local-first"],
  urls: {
    github: "https://github.com/p1rworks24-ops/Capixe",
    releases: "https://github.com/p1rworks24-ops/Capixe/releases",
    releasesApi: "https://api.github.com/repos/p1rworks24-ops/Capixe/releases?per_page=10",
    download: "https://github.com/p1rworks24-ops/Capixe/releases/download/v0.1.0-preview/Capixe-v0.1.0-preview-win64.zip",
    license: "https://github.com/p1rworks24-ops/Capixe/blob/master/LICENSE",
    issues: "https://github.com/p1rworks24-ops/Capixe/issues",
    bugReport: "https://github.com/p1rworks24-ops/Capixe/issues/new?template=bug_report.yml",
    featureRequest: "https://github.com/p1rworks24-ops/Capixe/issues/new?template=feature_request.yml",
    contact: "https://github.com/p1rworks24-ops/Capixe/issues/new?template=feature_request.yml",
  },
  screenshots: [
    {
      src: "assets/screenshots/images.png",
      alt: "Capixe Images - browse and analyze a selected screenshot folder",
      caption: "Images - choose a folder, analyze, and search",
      slot: "images",
    },
    {
      src: "assets/screenshots/home.png",
      alt: "Capixe Home - library overview, root folder, and capture bar",
      caption: "Home - see your whole library at a glance",
      slot: "home",
    },
    {
      src: "assets/screenshots/about.png",
      alt: "Capixe About - brand, version, repository, and feedback links",
      caption: "About - check version details and share feedback",
      slot: "about",
    },
  ],
  faq: [
    {
      q: "Is my data sent to the cloud?",
      a: "No. Capixe is local-first. Screenshots, settings, and the image-analysis index stay on your PC. Capixe does not upload your images to a Capixe cloud service.",
    },
    {
      q: "Does Capixe work offline?",
      a: "Yes. After you download the app, capture, browsing, local image analysis, and search work without an internet connection.",
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
