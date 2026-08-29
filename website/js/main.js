/**
 * Rootlize landing — minimal interactions (smooth scroll, content binding).
 */
(function () {
  "use strict";

  var C = window.CAPIXE;
  if (!C) return;

  function setHref(selector, url) {
    document.querySelectorAll(selector).forEach(function (el) {
      if (url) el.setAttribute("href", url);
    });
  }

  function setText(selector, text) {
    document.querySelectorAll(selector).forEach(function (el) {
      el.textContent = text;
    });
  }

  function resolveLatestDownload() {
    if (!C.urls.releasesApi || typeof window.fetch !== "function") return;

    window
      .fetch(C.urls.releasesApi, {
        headers: { Accept: "application/vnd.github+json" },
      })
      .then(function (response) {
        if (!response.ok) throw new Error("GitHub Releases request failed");
        return response.json();
      })
      .then(function (releases) {
        if (!Array.isArray(releases)) return;

        var asset = null;
        releases.some(function (release) {
          if (!release || release.draft || !Array.isArray(release.assets)) {
            return false;
          }
          asset =
            release.assets.find(function (item) {
              return /^(Rootlize|Capixe)-.*\.zip$/i.test(item.name || "");
            }) ||
            release.assets.find(function (item) {
              return /\.zip$/i.test(item.name || "");
            });
          return Boolean(asset);
        });

        if (asset && asset.browser_download_url) {
          setHref("[data-url-download]", asset.browser_download_url);
        }
      })
      .catch(function () {
        /* Keep the known working direct-download URL from content.js. */
      });
  }

  function renderGallery() {
    var gallery = document.getElementById("screenshot-gallery");
    if (!gallery || !Array.isArray(C.screenshots)) return;

    gallery.innerHTML = "";
    gallery.setAttribute("data-shot-count", String(C.screenshots.length));

    C.screenshots.forEach(function (shot) {
      var fig = document.createElement("figure");
      fig.className =
        "shot-card" + (shot.placeholder ? " shot-card--placeholder" : "");
      fig.setAttribute("data-slot", shot.slot || "");

      var img = document.createElement("img");
      img.src = shot.src;
      img.alt = shot.alt || "";
      img.loading = "lazy";
      /* Natural aspect — do not force a crop via width/height ratio */

      var button = document.createElement("button");
      button.className = "shot-button";
      button.type = "button";
      button.setAttribute(
        "aria-label",
        "View full size: " + (shot.caption || shot.alt || "screenshot")
      );
      button.addEventListener("click", function () {
        openLightbox(shot, button);
      });

      var cap = document.createElement("figcaption");
      cap.textContent = shot.caption || "";

      button.appendChild(img);
      fig.appendChild(button);
      fig.appendChild(cap);
      gallery.appendChild(fig);
    });
  }

  var lightboxReturnFocus = null;

  function openLightbox(shot, trigger) {
    var lightbox = document.getElementById("screenshot-lightbox");
    var image = document.getElementById("lightbox-image");
    var caption = document.getElementById("lightbox-caption");
    if (!lightbox || !image || !caption) return;

    lightboxReturnFocus = trigger || document.activeElement;
    image.src = shot.src;
    image.alt = shot.alt || "";
    caption.textContent = shot.caption || "";
    lightbox.classList.add("is-open");
    lightbox.setAttribute("aria-hidden", "false");
    document.body.classList.add("lightbox-open");

    var closeButton = lightbox.querySelector(".lightbox-close");
    if (closeButton) closeButton.focus();
  }

  function closeLightbox() {
    var lightbox = document.getElementById("screenshot-lightbox");
    var image = document.getElementById("lightbox-image");
    if (!lightbox || !lightbox.classList.contains("is-open")) return;

    lightbox.classList.remove("is-open");
    lightbox.setAttribute("aria-hidden", "true");
    document.body.classList.remove("lightbox-open");
    if (image) image.removeAttribute("src");

    if (lightboxReturnFocus && typeof lightboxReturnFocus.focus === "function") {
      lightboxReturnFocus.focus();
    }
    lightboxReturnFocus = null;
  }

  function setupLightbox() {
    var lightbox = document.getElementById("screenshot-lightbox");
    if (!lightbox) return;

    var closeButton = lightbox.querySelector(".lightbox-close");
    if (closeButton) closeButton.addEventListener("click", closeLightbox);

    lightbox.addEventListener("click", function (event) {
      if (event.target === lightbox) closeLightbox();
    });

    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape") closeLightbox();
    });
  }

  function renderBadges() {
    var row = document.getElementById("download-badges");
    if (!row || !Array.isArray(C.downloadBadges)) return;
    row.innerHTML = "";
    C.downloadBadges.forEach(function (label) {
      var span = document.createElement("span");
      span.className = "badge";
      span.textContent = label;
      row.appendChild(span);
    });
  }

  function renderFaq() {
    var list = document.getElementById("faq-list");
    if (!list || !Array.isArray(C.faq)) return;
    list.innerHTML = "";
    C.faq.forEach(function (item, index) {
      var details = document.createElement("details");
      details.className = "faq-item";
      if (index === 0) details.open = true;

      var summary = document.createElement("summary");
      summary.textContent = item.q;

      var body = document.createElement("p");
      body.textContent = item.a;

      details.appendChild(summary);
      details.appendChild(body);
      list.appendChild(details);
    });
  }

  function bindContent() {
    setText("[data-brand-name]", C.brand.name);
    setText("[data-brand-tagline]", C.brand.tagline);
    setText("[data-brand-description]", C.brand.description);

    setText("[data-version-channel]", C.version.channel);
    setText(
      "[data-version-label]",
      C.version.label || "Version " + C.version.number
    );
    setText("[data-version-number]", C.version.number);
    setText("[data-version-platform]", C.version.platform);

    setHref("[data-url-github]", C.urls.github);
    setHref("[data-url-releases]", C.urls.releases);
    setHref("[data-url-download]", C.urls.download);
    setHref("[data-url-license]", C.urls.license);
    setHref("[data-url-issues]", C.urls.issues);
    setHref("[data-url-bug]", C.urls.bugReport);
    setHref("[data-url-feature]", C.urls.featureRequest);
    setHref("[data-url-contact]", C.urls.contact);

    renderGallery();
    renderBadges();
    renderFaq();
  }

  function setupSmoothScroll() {
    document.querySelectorAll('a[href^="#"]').forEach(function (anchor) {
      anchor.addEventListener("click", function (e) {
        var id = anchor.getAttribute("href");
        if (!id || id === "#") return;
        var target = document.querySelector(id);
        if (!target) return;
        e.preventDefault();
        target.scrollIntoView({ behavior: "smooth", block: "start" });
      });
    });
  }

  function setupYear() {
    var el = document.getElementById("footer-year");
    if (el) el.textContent = String(new Date().getFullYear());
  }

  document.addEventListener("DOMContentLoaded", function () {
    bindContent();
    resolveLatestDownload();
    setupLightbox();
    setupSmoothScroll();
    setupYear();
  });
})();
