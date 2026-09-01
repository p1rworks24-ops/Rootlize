/**
 * Admin display helpers. No network. RPC payloads only.
 * Identity is auth user UUID. Installation IDs are never shown as User ID.
 */
(function (root) {
  "use strict";

  function shortId(value) {
    return String(value || "").replace(/-/g, "").slice(0, 8);
  }

  function userLabel(user) {
    if (!user) return "Guest";
    if (user.is_anonymous === true) {
      var guestId = shortId(user.user_id);
      return guestId ? "Guest \u00b7 " + guestId : "Guest";
    }
    var email = String(user.email || "").trim();
    if (email) return email;
    if (user.is_anonymous === false) {
      var accountId = shortId(user.user_id);
      return accountId ? "Account \u00b7 " + accountId : "Account";
    }
    return String(user.user_id || "Guest");
  }

  function userTypeLabel(user) {
    if (user && user.is_anonymous === true) return "Anonymous";
    if (user && user.is_anonymous === false) return "Account";
    return String((user && user.email) || "").trim() ? "Account" : "—";
  }

  function statusLabel(user) {
    if (!user) return "Anonymous session";
    if (user.is_anonymous === true) {
      if (user.ai_limit_reached) return "AI limit reached";
      if (Number(user.ai_used_micros || 0) <= 0) return "Never used AI";
      return "Active Guest";
    }
    return "Account";
  }

  function planLabel(plan) {
    var id = String(plan || "").trim().toLowerCase();
    if (id === "prototype") return "Prototype";
    if (id === "free") return "Free";
    if (id === "next") return "Next";
    if (id === "pro") return "Pro";
    return id ? String(plan) : "—";
  }

  function formatUsdAmount(micros) {
    return "$" + (Number(micros || 0) / 1000000).toFixed(2);
  }

  function formatUsdPair(usedMicros, capMicros) {
    return formatUsdAmount(usedMicros) + " / " + formatUsdAmount(capMicros);
  }

  function lastSeenAt(user) {
    if (!user) return "";
    var values = [
      user.device_last_seen_at,
      user.ai_last_at,
      user.last_event_at,
      user.last_sign_in_at,
    ];
    var latest = "";
    var latestMs = 0;
    values.forEach(function (value) {
      if (!value) return;
      var ms = Date.parse(value);
      if (Number.isNaN(ms)) return;
      if (ms >= latestMs) {
        latestMs = ms;
        latest = value;
      }
    });
    return latest;
  }

  function matchesFilter(user, filter) {
    var key = String(filter || "all");
    if (key === "all" || !key) return true;
    if (key === "anonymous") return Boolean(user && user.is_anonymous === true);
    if (key === "account") return Boolean(user && user.is_anonymous !== true);
    if (key === "prototype") return String((user && user.plan) || "") === "prototype";
    if (key === "ai_limit") return Boolean(user && user.ai_limit_reached);
    return true;
  }

  function matchesQuery(user, query) {
    var q = String(query || "").trim().toLowerCase();
    if (!q) return true;
    var hay = [
      userLabel(user),
      userTypeLabel(user),
      planLabel(user && user.plan),
      statusLabel(user),
      user && user.email,
      user && user.user_id,
      user && user.plan,
    ]
      .concat(
        ((user && user.devices) || []).map(function (device) {
          return device && device.device_id;
        })
      )
      .join(" ")
      .toLowerCase();
    return hay.indexOf(q) !== -1;
  }

  function compareUsers(a, b, sortKey) {
    var key = String(sortKey || "signup_at");
    var av = a ? a[key] : "";
    var bv = b ? b[key] : "";
    if (key === "email") {
      av = userLabel(a).toLowerCase();
      bv = userLabel(b).toLowerCase();
    }
    av = av == null ? "" : av;
    bv = bv == null ? "" : bv;
    if (av < bv) return -1;
    if (av > bv) return 1;
    return String((a && a.user_id) || "").localeCompare(String((b && b.user_id) || ""));
  }

  root.RootlizeAdminDisplay = {
    shortId: shortId,
    userLabel: userLabel,
    userTypeLabel: userTypeLabel,
    planLabel: planLabel,
    statusLabel: statusLabel,
    formatUsdAmount: formatUsdAmount,
    formatUsdPair: formatUsdPair,
    lastSeenAt: lastSeenAt,
    matchesFilter: matchesFilter,
    matchesQuery: matchesQuery,
    compareUsers: compareUsers,
  };
})(window);
