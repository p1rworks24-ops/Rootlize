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

  function expectedDownloadName() {
    return (C.urls && C.urls.downloadAsset) || "Rootlize-v0.1.0-preview-win64.zip";
  }

  function setDownloadPending() {
    document.querySelectorAll("[data-url-download]").forEach(function (el) {
      el.setAttribute("href", "#download");
      el.removeAttribute("target");
      el.removeAttribute("rel");
      el.setAttribute("aria-disabled", "true");
      el.classList.add("is-pending");
    });
    document.querySelectorAll("[data-url-releases]").forEach(function (el) {
      el.setAttribute("href", "#download");
      el.removeAttribute("target");
      el.removeAttribute("rel");
    });
    setText(
      "[data-download-meta]",
      "Windows 10 / 11 · ZIP available after the GitHub Release"
    );
  }

  function setDownloadLive(assetUrl, releaseUrl) {
    document.querySelectorAll("[data-url-download]").forEach(function (el) {
      el.setAttribute("href", assetUrl);
      el.setAttribute("target", "rootlize-download");
      el.removeAttribute("aria-disabled");
      el.classList.remove("is-pending");
    });
    if (releaseUrl) {
      document.querySelectorAll("[data-url-releases]").forEach(function (el) {
        el.setAttribute("href", releaseUrl);
        el.setAttribute("target", "_blank");
        el.setAttribute("rel", "noopener noreferrer");
      });
    }
    setText("[data-download-meta]", "Windows 10 / 11 · Free Preview");
  }

  function setText(selector, text) {
    document.querySelectorAll(selector).forEach(function (el) {
      el.textContent = text;
    });
  }

  function resolveLatestDownload() {
    var expected = expectedDownloadName().toLowerCase();
    if (!C.urls.releasesApi || typeof window.fetch !== "function") {
      setDownloadPending();
      return;
    }

    window
      .fetch(C.urls.releasesApi, {
        headers: { Accept: "application/vnd.github+json" },
      })
      .then(function (response) {
        if (!response.ok) throw new Error("GitHub Releases request failed");
        return response.json();
      })
      .then(function (releases) {
        if (!Array.isArray(releases)) {
          setDownloadPending();
          return;
        }

        var match = null;
        releases.some(function (release) {
          if (!release || release.draft || !Array.isArray(release.assets)) {
            return false;
          }
          var asset = release.assets.find(function (item) {
            return String(item.name || "").toLowerCase() === expected;
          });
          if (!asset || !asset.browser_download_url) return false;
          match = { asset: asset, release: release };
          return true;
        });

        if (match) {
          setDownloadLive(
            match.asset.browser_download_url,
            match.release.html_url || C.urls.releases
          );
          return;
        }
        setDownloadPending();
      })
      .catch(function () {
        setDownloadPending();
      });
  }

  function prefersReducedMotion() {
    return (
      typeof window.matchMedia === "function" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches
    );
  }

  function renderCarousel() {
    var viewport = document.getElementById("carousel-viewport");
    var dots = document.getElementById("carousel-dots");
    var caption = document.getElementById("carousel-caption");
    var root = document.getElementById("hero-carousel");
    if (!viewport || !dots || !Array.isArray(C.screenshots) || !C.screenshots.length) {
      return;
    }

    viewport.innerHTML = "";
    dots.innerHTML = "";

    C.screenshots.forEach(function (shot, index) {
      var slide = document.createElement("figure");
      slide.className = "showcase-slide" + (index === 0 ? " is-active" : "");
      slide.setAttribute("data-slot", shot.slot || "");
      slide.setAttribute("aria-hidden", index === 0 ? "false" : "true");

      var img = document.createElement("img");
      img.src = shot.src;
      img.alt = shot.alt || "";
      img.decoding = "async";
      if (index === 0) {
        img.setAttribute("fetchpriority", "high");
      } else {
        img.loading = "lazy";
      }

      var button = document.createElement("button");
      button.type = "button";
      button.setAttribute(
        "aria-label",
        "View full size: " + (shot.caption || shot.alt || "screenshot")
      );
      button.addEventListener("click", function () {
        openLightbox(shot, button);
      });
      button.appendChild(img);
      slide.appendChild(button);
      viewport.appendChild(slide);

      var dot = document.createElement("button");
      dot.type = "button";
      dot.className = "showcase-dot" + (index === 0 ? " is-active" : "");
      dot.setAttribute("role", "tab");
      dot.setAttribute("aria-label", shot.caption || shot.alt || "Screen " + (index + 1));
      dot.addEventListener("click", function () {
        goTo(index, true);
      });
      dots.appendChild(dot);
    });

    if (caption) caption.textContent = C.screenshots[0].caption || "";

    var index = 0;
    var timer = null;
    var delay = 5200;

    function slides() {
      return viewport.querySelectorAll(".showcase-slide");
    }

    function goTo(next, user) {
      var nodes = slides();
      var total = nodes.length;
      if (!total) return;
      next = (next + total) % total;
      if (next === index) return;

      nodes[index].classList.remove("is-active");
      nodes[index].setAttribute("aria-hidden", "true");
      nodes[next].classList.add("is-active");
      nodes[next].setAttribute("aria-hidden", "false");

      dots.querySelectorAll(".showcase-dot").forEach(function (dot, i) {
        dot.classList.toggle("is-active", i === next);
      });
      if (caption) caption.textContent = C.screenshots[next].caption || "";
      index = next;
      if (user) restart();
    }

    function next() {
      goTo(index + 1, false);
    }

    function stop() {
      if (timer) {
        window.clearInterval(timer);
        timer = null;
      }
    }

    function start() {
      stop();
      if (prefersReducedMotion() || document.hidden) return;
      timer = window.setInterval(next, delay);
    }

    function restart() {
      if (!prefersReducedMotion()) start();
    }

    var prevBtn = root.querySelector("[data-carousel-prev]");
    var nextBtn = root.querySelector("[data-carousel-next]");
    if (prevBtn) {
      prevBtn.addEventListener("click", function () {
        goTo(index - 1, true);
      });
    }
    if (nextBtn) {
      nextBtn.addEventListener("click", function () {
        goTo(index + 1, true);
      });
    }

    root.addEventListener("mouseenter", stop);
    root.addEventListener("mouseleave", start);
    root.addEventListener("focusin", stop);
    root.addEventListener("focusout", start);
    document.addEventListener("visibilitychange", function () {
      if (document.hidden) stop();
      else start();
    });

    var touchX = null;
    viewport.addEventListener(
      "touchstart",
      function (event) {
        if (!event.changedTouches || !event.changedTouches[0]) return;
        touchX = event.changedTouches[0].clientX;
        stop();
      },
      { passive: true }
    );
    viewport.addEventListener(
      "touchend",
      function (event) {
        if (touchX == null || !event.changedTouches || !event.changedTouches[0]) {
          start();
          return;
        }
        var dx = event.changedTouches[0].clientX - touchX;
        touchX = null;
        if (Math.abs(dx) > 40) goTo(index + (dx < 0 ? 1 : -1), true);
        else start();
      },
      { passive: true }
    );

    root.addEventListener("keydown", function (event) {
      if (event.key === "ArrowLeft") {
        event.preventDefault();
        goTo(index - 1, true);
      } else if (event.key === "ArrowRight") {
        event.preventDefault();
        goTo(index + 1, true);
      }
    });

    start();
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
    setHref("[data-url-license]", C.urls.license);
    setHref("[data-url-issues]", C.urls.issues);
    setHref("[data-url-bug]", C.urls.bugReport);
    setHref("[data-url-feature]", C.urls.featureRequest);
    setHref("[data-url-contact]", C.urls.contact);
    setHref("[data-url-privacy]", C.urls.privacy);
    setHref("[data-url-terms]", C.urls.terms);

    renderCarousel();
    renderBadges();
    renderFaq();
  }

  function setupReveal() {
    var nodes = document.querySelectorAll(".reveal");
    if (!nodes.length) return;
    if (prefersReducedMotion() || typeof window.IntersectionObserver !== "function") {
      nodes.forEach(function (el) {
        el.classList.add("is-in");
      });
      return;
    }
    var observer = new window.IntersectionObserver(
      function (entries) {
        entries.forEach(function (entry) {
          if (!entry.isIntersecting) return;
          entry.target.classList.add("is-in");
          observer.unobserve(entry.target);
        });
      },
      { threshold: 0.16, rootMargin: "0px 0px -8% 0px" }
    );
    nodes.forEach(function (el) {
      observer.observe(el);
    });
  }

  function setupConceptMotion() {
    var nodes = document.querySelectorAll(".viz");
    if (!nodes.length) return;
    if (prefersReducedMotion()) return;
    if (typeof window.IntersectionObserver !== "function") {
      nodes.forEach(function (el) {
        el.classList.add("is-playing");
      });
      return;
    }
    var visible = [];
    var observer = new window.IntersectionObserver(
      function (entries) {
        entries.forEach(function (entry) {
          if (entry.isIntersecting) {
            if (visible.indexOf(entry.target) === -1) visible.push(entry.target);
          } else {
            visible = visible.filter(function (node) {
              return node !== entry.target;
            });
          }
          entry.target.classList.toggle(
            "is-playing",
            entry.isIntersecting && !document.hidden
          );
        });
      },
      { threshold: 0.22 }
    );
    nodes.forEach(function (el) {
      observer.observe(el);
    });
    document.addEventListener("visibilitychange", function () {
      visible.forEach(function (el) {
        el.classList.toggle("is-playing", !document.hidden);
      });
    });
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
    setDownloadPending();
    resolveLatestDownload();
    setupLightbox();
    setupReveal();
    setupConceptMotion();
    setupSmoothScroll();
    setupYear();
  });
})();
