/** Rootlize landing-page content. Internal `window.CAPIXE` key is unchanged. */
window.CAPIXE = {
  brand: {
    name: "Rootlize",
    tagline: "Your Local Workspace.",
    description: "Find, organize, and automate work with the images already on your PC — without moving them to a Rootlize cloud.",
  },
  hero: {
    eyebrow: "Prototype Preview · Windows",
    description:
      "Find images already on your Windows PC, organize what you find, and save repeating work as a Workflow.",
    kicker: "Describe it. AI builds the workflow.",
    signupNote: "No sign-up required",
    proof: "Prototype Preview · v0.1.0-preview · Features may change",
  },
  version: {
    channel: "Prototype Preview",
    number: "0.1.0-preview",
    get label() { return "v" + this.number.replace(/^v/, ""); },
    platform: "Windows",
  },
  downloadBadges: ["Windows 10 / 11", "Free", "No sign-up", "Local-first"],
  urls: {
    github: "https://github.com/p1rworks24-ops/Rootlize",
    releases: "https://github.com/p1rworks24-ops/Rootlize/releases",
    releasesApi: "https://api.github.com/repos/p1rworks24-ops/Rootlize/releases?per_page=10",
    downloadAsset: "Rootlize-v0.1.0-preview-win64.zip",
    downloadTag: "v0.1.0-preview.1",
    download:
      "https://github.com/p1rworks24-ops/Rootlize/releases/download/v0.1.0-preview.1/Rootlize-v0.1.0-preview-win64.zip",
    license: "https://github.com/p1rworks24-ops/Rootlize/blob/master/LICENSE",
    issues: "https://github.com/p1rworks24-ops/Rootlize/issues",
    bugReport: "https://github.com/p1rworks24-ops/Rootlize/issues/new?template=bug_report.yml",
    featureRequest: "https://github.com/p1rworks24-ops/Rootlize/issues/new?template=feature_request.yml",
    contact: "https://github.com/p1rworks24-ops/Rootlize/issues/new?template=feature_request.yml",
    privacy: "/privacy",
    terms: "/terms",
  },
  // Hero carousel is data-driven. Keep 3 distinct product shots; extra
  // near-duplicate screens can be removed without changing the renderer.
  screenshots: [
    {
      src: "assets/screenshots/images.png",
      full: "assets/screenshots/images-full.png",
      alt: "Rootlize Images workspace",
      caption: "Find — search the folder already on your PC",
      slot: "images",
    },
    {
      src: "assets/screenshots/ask-ai.png",
      full: "assets/screenshots/ask-ai-full.png",
      alt: "Rootlize Ask AI panel",
      caption: "Ask AI — find and organize in your own words",
      slot: "ask-ai",
    },
    {
      src: "assets/screenshots/automation.png",
      full: "assets/screenshots/automation-full.png",
      alt: "Rootlize Automation page",
      caption: "Automate — describe it, and AI builds an editable Workflow",
      slot: "automation",
    },
  ],
  faq: [
    {
      q: "Is Rootlize free?",
      a: "Yes. This Prototype Preview is free to download and try. There is no subscription. AI usage is limited during the Prototype.",
    },
    {
      q: "Do I need an account?",
      a: "No. The public Prototype does not require sign-up or login. You can download it and start as a guest.",
    },
    {
      q: "Does Rootlize upload my images?",
      a: "Rootlize is not a cloud library. It does not move your image collection to Rootlize cloud storage. You point it at folders already on this PC. If you agree to use Ask AI, the first analysis may send those images to an external AI. After that, Meaning Search uses saved facts instead of resending images every time.",
    },
    {
      q: "Is there a Mac version?",
      a: "Not yet. This Prototype is Windows 10 / Windows 11, 64-bit only.",
    },
    {
      q: "Is this a finished product?",
      a: "No. Rootlize is a Prototype Preview (v0.1.0-preview). Features may change. Feedback is welcome.",
    },
    {
      q: "Does AI organize my files by itself?",
      a: "No. Rootlize is not an AI file organizer that rearranges your folders on its own. You describe the work, AI builds an editable Workflow from existing blocks, and you review a preview before anything runs.",
    },
    {
      q: "What runs locally, and when does AI go online?",
      a: "Filename, tag, and text-in-image search run on this PC. Ask AI needs the internet after you agree. Until you agree, Rootlize does not start sending images for AI analysis. After the Prototype AI limit, local search and organize still work.",
    },
    {
      q: "Do I need to install Python?",
      a: "No. The download is a portable Windows ZIP. Extract it completely, keep Rootlize.exe together with the _internal folder, then run Rootlize.exe.",
    },
    {
      q: "Windows warned me about the download. Is that expected?",
      a: "Yes. This Prototype is unsigned, so Windows SmartScreen may show a warning. Continue only if you downloaded the ZIP from rootlize.com, then choose More info → Run anyway.",
    },
  ],
};
