/**
 * Landing-page analytics. Event name + visitor id only.
 * Operator opt-out: localStorage rootlize_analytics_opt_out = true
 * Enable:  /?analytics=off
 * Disable: /?analytics=on
 */
(function () {
  "use strict";

  var OPT_OUT_KEY = "rootlize_analytics_opt_out";
  var VISITOR_KEY = "rootlize_visitor_id";
  var FIRST_VISIT_KEY = "rootlize_lp_visit_sent";
  var ALLOWED = { lp_visit: true, page_view: true, download_click: true };

  function config() {
    var cfg = window.ROOTLIZE_SUPABASE || {};
    return {
      url: String(cfg.url || "").replace(/\/$/, ""),
      key: String(cfg.publishableKey || ""),
    };
  }

  function isOptedOut() {
    try {
      return window.localStorage.getItem(OPT_OUT_KEY) === "true";
    } catch (err) {
      return false;
    }
  }

  function setOptOut(enabled) {
    try {
      if (enabled) {
        window.localStorage.setItem(OPT_OUT_KEY, "true");
      } else {
        window.localStorage.removeItem(OPT_OUT_KEY);
      }
    } catch (err) {
      /* ignore quota / private mode */
    }
  }

  function visitorId() {
    try {
      var existing = window.localStorage.getItem(VISITOR_KEY);
      if (existing && existing.length >= 8 && existing.length <= 64) {
        return existing;
      }
      var id =
        typeof crypto !== "undefined" && crypto.randomUUID
          ? crypto.randomUUID()
          : "v-" + String(Date.now()) + "-" + String(Math.random()).slice(2, 10);
      window.localStorage.setItem(VISITOR_KEY, id);
      return id;
    } catch (err) {
      return "v-session";
    }
  }

  function queryFlag() {
    try {
      var params = new URLSearchParams(window.location.search || "");
      var value = String(params.get("analytics") || "").toLowerCase();
      if (value === "off" || value === "0" || value === "false") return "off";
      if (value === "on" || value === "1" || value === "true") return "on";
    } catch (err) {
      /* ignore */
    }
    return "";
  }

  function showNotice(text) {
    var existing = document.getElementById("rootlize-analytics-notice");
    if (existing) existing.remove();
    var el = document.createElement("div");
    el.id = "rootlize-analytics-notice";
    el.setAttribute("role", "status");
    el.textContent = text;
    el.style.cssText =
      "position:fixed;z-index:9999;right:16px;bottom:16px;max-width:22rem;" +
      "padding:10px 12px;border-radius:10px;background:#111827;color:#fff;" +
      "font:500 0.875rem/1.4 'Source Sans 3',sans-serif;box-shadow:0 8px 24px rgba(0,0,0,.18);";
    document.body.appendChild(el);
    window.setTimeout(function () {
      if (el.parentNode) el.parentNode.removeChild(el);
    }, 4000);
  }

  function applyOperatorFlag() {
    var flag = queryFlag();
    if (!flag) return false;
    if (flag === "off") {
      setOptOut(true);
      showNotice("Analytics opt-out is on for this browser.");
      return true;
    }
    setOptOut(false);
    showNotice("Analytics opt-out is off for this browser.");
    return false;
  }

  function send(eventName) {
    if (!ALLOWED[eventName] || isOptedOut()) return;
    var cfg = config();
    if (!cfg.url || !cfg.key || typeof window.fetch !== "function") return;
    window
      .fetch(cfg.url + "/rest/v1/website_analytics", {
        method: "POST",
        headers: {
          apikey: cfg.key,
          Authorization: "Bearer " + cfg.key,
          "Content-Type": "application/json",
          Prefer: "return=minimal",
        },
        body: JSON.stringify({
          visitor_id: visitorId(),
          event_name: eventName,
        }),
        keepalive: true,
      })
      .catch(function () {
        /* analytics must never block the page */
      });
  }

  function markFirstVisit() {
    try {
      return window.localStorage.getItem(FIRST_VISIT_KEY) === "1";
    } catch (err) {
      return false;
    }
  }

  function rememberFirstVisit() {
    try {
      window.localStorage.setItem(FIRST_VISIT_KEY, "1");
    } catch (err) {
      /* ignore */
    }
  }

  function trackPage() {
    if (isOptedOut()) return;
    if (!markFirstVisit()) {
      send("lp_visit");
      rememberFirstVisit();
    }
    send("page_view");
  }

  function onDownloadClick(event) {
    var target = event.target;
    if (!target || typeof target.closest !== "function") return;
    if (!target.closest("[data-url-download]")) return;
    send("download_click");
  }

  window.__rootlizeAnalytics = {
    optOut: function () {
      setOptOut(true);
      return "opted_out";
    },
    optIn: function () {
      setOptOut(false);
      return "opted_in";
    },
    status: function () {
      return isOptedOut() ? "opted_out" : "active";
    },
  };

  document.addEventListener("click", onDownloadClick, true);
  document.addEventListener("DOMContentLoaded", function () {
    var skipThisLoad = applyOperatorFlag();
    if (!skipThisLoad) trackPage();
  });
})();
