(function () {
  "use strict";

  var cfg = window.ROOTLIZE_SUPABASE || {};
  var createClient = window.supabase && window.supabase.createClient;
  var display = window.RootlizeAdminDisplay;
  if (!createClient || !cfg.url || !cfg.publishableKey || !display) {
    document.body.innerHTML = "<p>Admin client is not configured.</p>";
    return;
  }

  var client = createClient(cfg.url, cfg.publishableKey, {
    auth: {
      persistSession: true,
      detectSessionInUrl: true,
      flowType: "pkce",
    },
  });
  var api = new window.RootlizeAdminApi(client);
  var selectedUserId = "";
  var loadedUsers = [];

  var loginView = document.getElementById("login-view");
  var appView = document.getElementById("app-view");
  var authError = document.getElementById("auth-error");
  var appError = document.getElementById("app-error");
  var userFilter = document.getElementById("user-filter");
  var userSearch = document.getElementById("user-search");

  function show(el, on) {
    el.classList.toggle("hidden", !on);
  }

  function setText(id, text) {
    var el = document.getElementById(id);
    if (el) el.textContent = text;
  }

  function formatUsd(micros) {
    var value = Number(micros || 0) / 1000000;
    if (!value) return "$0";
    if (value < 0.01) return "$" + value.toFixed(4);
    return "$" + value.toFixed(2);
  }

  function formatTime(value) {
    if (!value) return "—";
    var date = new Date(value);
    if (Number.isNaN(date.getTime())) return "—";
    var pad = function (n) {
      return String(n).padStart(2, "0");
    };
    return (
      date.getFullYear() +
      "-" +
      pad(date.getMonth() + 1) +
      "-" +
      pad(date.getDate()) +
      " " +
      pad(date.getHours()) +
      ":" +
      pad(date.getMinutes())
    );
  }

  function authMessage(error) {
    var text = String((error && (error.code || error.message)) || error || "");
    if (text.indexOf("not_admin") !== -1) {
      return "This account is not an admin.";
    }
    if (text.indexOf("not_authenticated") !== -1) {
      return "Sign in required.";
    }
    return text || "Request failed.";
  }

  function statusBadge(user) {
    var label = display.statusLabel(user);
    var cls = "badge-muted";
    if (label === "Active Guest") cls = "badge-ok";
    if (label === "AI limit reached") cls = "badge-warn";
    if (label === "Account") cls = "badge-info";
    return '<span class="badge ' + cls + '">' + escapeHtml(label) + "</span>";
  }

  function visibleUsers() {
    var filter = userFilter ? userFilter.value : "all";
    var query = userSearch ? userSearch.value : "";
    return loadedUsers
      .filter(function (user) {
        return display.matchesFilter(user, filter) && display.matchesQuery(user, query);
      })
      .slice()
      .sort(function (a, b) {
        return display.compareUsers(b, a, "signup_at");
      });
  }

  function renderOverview(data) {
    var lp = (data && data.lp) || {};
    var downloads = (data && data.downloads) || {};
    var users = (data && data.users) || {};
    var apiCost = (data && data.api_cost) || {};
    var tutorial = (data && data.tutorial) || {};
    var categories = apiCost.by_category || {};

    setText("kpi-visitors", String(lp.unique_visitors || 0));
    setText("kpi-pageviews", (lp.page_views || 0) + " page views");
    setText("kpi-downloads", String(downloads.clicks || 0));
    setText("kpi-github-downloads", "User CTA clicks");
    setText("kpi-users", String(users.total || 0));
    setText(
      "kpi-users-sub",
      "Today " + (users.today || 0) + " · 7 days " + (users.last_7_days || 0)
    );
    setText("kpi-guests", String(users.anonymous || 0));
    setText(
      "kpi-guests-sub",
      "Prototype " + (users.prototype || 0)
    );
    setText("kpi-accounts", String(users.account || 0));
    setText("kpi-accounts-sub", "Email / OAuth");
    setText("kpi-ai-users", String(users.used_ai || 0));
    setText(
      "kpi-ai-users-sub",
      "Limit reached " + (users.ai_limit_reached || 0)
    );
    setText("kpi-api", formatUsd(apiCost.total_usd_micros));
    setText(
      "kpi-api-sub",
      "Today " +
        formatUsd(apiCost.today_usd_micros) +
        " · Vision " +
        formatUsd(categories.vision_usd_micros) +
        " · Meaning " +
        formatUsd(categories.meaning_search_usd_micros)
    );
    setText("kpi-tutorial", String(tutorial.completed || 0));
    setText(
      "kpi-tutorial-sub",
      "Started " +
        (tutorial.started || 0) +
        " · " +
        (tutorial.completion_rate || 0) +
        "% complete"
    );
  }

  function renderUsers() {
    var body = document.getElementById("users-body");
    var users = visibleUsers();
    body.innerHTML = "";
    if (!loadedUsers.length) {
      body.innerHTML =
        '<tr><td colspan="7" class="muted">No users yet.</td></tr>';
      return;
    }
    if (!users.length) {
      body.innerHTML =
        '<tr><td colspan="7" class="muted">No users match this filter.</td></tr>';
      return;
    }
    users.forEach(function (user) {
      var tr = document.createElement("tr");
      tr.dataset.userId = user.user_id;
      if (user.user_id === selectedUserId) tr.className = "is-selected";
      tr.innerHTML =
        '<td><div class="user-cell"><strong>' +
        escapeHtml(display.userLabel(user)) +
        '</strong><span class="muted">' +
        escapeHtml(display.shortId(user.user_id) || "—") +
        "</span></div></td><td>" +
        escapeHtml(display.userTypeLabel(user)) +
        "</td><td>" +
        escapeHtml(display.planLabel(user.plan)) +
        "</td><td>" +
        escapeHtml(display.formatUsdPair(user.ai_used_micros, user.ai_hard_cap_micros)) +
        "</td><td>" +
        statusBadge(user) +
        "</td><td>" +
        escapeHtml(formatTime(user.signup_at)) +
        "</td><td>" +
        escapeHtml(formatTime(display.lastSeenAt(user))) +
        "</td>";
      tr.addEventListener("click", function () {
        selectedUserId = user.user_id;
        Array.prototype.forEach.call(body.querySelectorAll("tr"), function (row) {
          row.classList.toggle("is-selected", row === tr);
        });
        renderDetail(user, null);
        loadHistory(user);
      });
      body.appendChild(tr);
    });
  }

  function escapeHtml(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function renderDevices(user) {
    var body = document.getElementById("devices-body");
    var devices = (user && user.devices) || [];
    var authLabel = display.userLabel(user);
    var authId = user && user.user_id ? String(user.user_id) : "";
    body.innerHTML = "";
    if (!user) {
      body.innerHTML =
        '<tr><td colspan="5" class="muted">Select a user.</td></tr>';
      return;
    }
    if (!devices.length) {
      body.innerHTML =
        '<tr><td colspan="5" class="muted">No installation registered.</td></tr>';
      return;
    }
    devices.forEach(function (device) {
      var tr = document.createElement("tr");
      tr.innerHTML =
        "<td>" +
        escapeHtml((device && device.device_id) || "—") +
        "</td><td>" +
        escapeHtml(formatTime(device && device.last_seen_at)) +
        "</td><td>" +
        escapeHtml((device && device.platform) || "—") +
        "</td><td>" +
        escapeHtml((device && device.device_name) || "—") +
        "</td><td>" +
        escapeHtml(authLabel) +
        "<div class=\"muted\">" +
        escapeHtml(authId) +
        "</div></td>";
      body.appendChild(tr);
    });
  }

  function renderDetail(user, payload) {
    var detail = document.getElementById("user-detail");
    var merged = Object.assign({}, user || {}, payload || {});
    if (!merged.user_id) {
      show(detail, false);
      setText("history-user", "Select a user.");
      renderDevices(null);
      return;
    }
    show(detail, true);
    setText("history-user", display.userLabel(merged));
    detail.innerHTML =
      "<dt>User</dt><dd>" +
      escapeHtml(display.userLabel(merged)) +
      "</dd><dt>Type</dt><dd>" +
      escapeHtml(display.userTypeLabel(merged)) +
      "</dd><dt>Status</dt><dd>" +
      escapeHtml(display.statusLabel(merged)) +
      "</dd><dt>Plan</dt><dd>" +
      escapeHtml(display.planLabel(merged.plan)) +
      "</dd><dt>User ID</dt><dd>" +
      escapeHtml(merged.user_id || "—") +
      "</dd><dt>Email</dt><dd>" +
      escapeHtml(merged.is_anonymous ? "—" : merged.email || "—") +
      "</dd><dt>AI usage</dt><dd>" +
      escapeHtml(display.formatUsdPair(merged.ai_used_micros, merged.ai_hard_cap_micros)) +
      "</dd><dt>Remaining</dt><dd>" +
      escapeHtml(display.formatUsdAmount(merged.ai_remaining_micros)) +
      "</dd><dt>Latest AI</dt><dd>" +
      escapeHtml(formatTime(merged.ai_last_at)) +
      "</dd><dt>Created</dt><dd>" +
      escapeHtml(formatTime(merged.signup_at)) +
      "</dd><dt>First seen</dt><dd>" +
      escapeHtml(formatTime(merged.first_seen_at || merged.signup_at)) +
      "</dd><dt>Last seen</dt><dd>" +
      escapeHtml(formatTime(display.lastSeenAt(merged))) +
      "</dd><dt>Launches / sessions</dt><dd>" +
      escapeHtml(String(merged.launch_count == null ? "—" : merged.launch_count)) + " / " +
      escapeHtml(String(merged.session_count == null ? "—" : merged.session_count)) +
      "</dd><dt>Second session reached</dt><dd>" +
      escapeHtml(merged.second_session_reached ? "Yes" : "No") +
      "</dd>";
    renderDevices(merged);
  }

  function renderHistory(payload) {
    var list = document.getElementById("history-list");
    var events = (payload && (payload.timeline || payload.events)) || [];
    list.innerHTML = "";
    if (!events.length) {
      list.innerHTML = '<li class="muted">No events yet.</li>';
      return;
    }
    events.forEach(function (event) {
      var item = document.createElement("li");
      var time = document.createElement("time");
      time.textContent = formatTime(event.occurred_at);
      var label = document.createElement("span");
      var details = event.payload || {};
      var suffix = [];
      if (details.operation) suffix.push(details.operation);
      if (details.status) suffix.push(details.status);
      if (details.search_kind) suffix.push(details.search_kind + " search");
      label.textContent = api.eventLabel(event.event_name) + (suffix.length ? " · " + suffix.join(" · ") : "");
      item.appendChild(time);
      item.appendChild(label);
      list.appendChild(item);
    });
  }

  function renderAiRequests(payload) {
    var body = document.getElementById("ai-requests-body");
    var rows = (payload && payload.ai_requests) || [];
    body.innerHTML = "";
    if (!rows.length) {
      body.innerHTML = '<tr><td colspan="5" class="muted">No AI requests recorded.</td></tr>';
      return;
    }
    rows.forEach(function (row) {
      var tr = document.createElement("tr");
      tr.innerHTML = "<td>" + escapeHtml(formatTime(row.occurred_at)) + "</td><td>" +
        escapeHtml(row.operation || "—") + "</td><td>" + escapeHtml(row.status || "—") +
        "</td><td>" + escapeHtml(formatUsd(row.actual_cost_micros)) + "</td><td>" +
        escapeHtml(row.request_id_short || "—") + "</td>";
      body.appendChild(tr);
    });
  }

  function renderFeedback(payload) {
    var host = document.getElementById("feedback-detail");
    var entries = (payload && payload.feedback) || [];
    host.innerHTML = "";
    if (!entries.length) {
      host.textContent = "No feedback submitted.";
      return;
    }
    entries.forEach(function (entry) {
      var block = document.createElement("div");
      block.className = "feedback-entry";
      var rows = [
        ["Submitted", formatTime(entry.submitted_at)], ["App version", entry.app_version || "—"],
        ["Feedback version", entry.feedback_version || "—"], ["Most useful", entry.most_useful || "—"],
        ["Would use", entry.would_use || "—"], ["Easier", entry.easier_than_current || "—"],
        ["Willingness to pay", entry.willingness_to_pay || "—"], ["Confusing feedback", entry.confusing_text || "—"]
      ];
      rows.forEach(function (pair) {
        var row = document.createElement("p");
        row.innerHTML = "<strong>" + escapeHtml(pair[0]) + ":</strong> " + escapeHtml(pair[1]);
        block.appendChild(row);
      });
      host.appendChild(block);
    });
  }

  function renderFunnel(data) {
    var body = document.getElementById("funnel-body");
    var labels = {
      created: "Guest / Account created", first_launch: "First launch", folder_added: "Folder added",
      first_search: "First search", first_ai_use: "First AI use", workflow_created: "Workflow created",
      workflow_previewed: "Workflow previewed", workflow_executed: "Workflow executed",
      file_action_completed: "File action completed", second_session: "Second session",
      feedback_submitted: "Feedback submitted", account_created: "Account created"
    };
    body.innerHTML = "";
    Object.keys(labels).forEach(function (key) {
      var value = (data && data[key]) || {};
      var tr = document.createElement("tr");
      tr.innerHTML = "<td>" + escapeHtml(labels[key]) + "</td><td>" +
        escapeHtml(String(value.users || 0)) + "</td><td>" +
        escapeHtml(value.installations == null ? "—" : String(value.installations)) + "</td>";
      body.appendChild(tr);
    });
  }

  function loadHistory(user) {
    Promise.all([api.getUserActivity(user.user_id), api.getProductUserDetail(user.user_id)])
      .then(function (results) {
        var legacy = results[0] || {};
        var product = results[1] || {};
        renderDetail(user, Object.assign({}, legacy, product));
        renderHistory(product.timeline ? product : legacy);
        renderAiRequests(product);
        renderFeedback(product);
      })
      .catch(function (error) {
        show(appError, true);
        appError.textContent = authMessage(error);
      });
  }

  function loadDashboard() {
    show(appError, false);
    return Promise.all([
      api.getOverview(),
      api.getUsers(),
      api.getApiUsage(),
      api.getProductFunnel(),
    ])
      .then(function (results) {
        var overview = results[0] || {};
        if (results[2]) overview.api_cost = results[2];
        renderFunnel(results[3] || {});
        loadedUsers = Array.isArray(results[1]) ? results[1] : [];
        renderOverview(overview);
        renderUsers();
        if (selectedUserId) {
          var match = loadedUsers.filter(function (user) {
            return user.user_id === selectedUserId;
          })[0];
          if (match) {
            renderDetail(match, null);
            loadHistory(match);
          }
        }
      })
      .catch(function (error) {
        show(appError, true);
        appError.textContent = authMessage(error);
        if (String(error && error.code).indexOf("not_admin") !== -1) {
          throw error;
        }
      });
  }

  function showApp(session) {
    show(loginView, false);
    show(appView, true);
    setText("signed-in-email", (session.user && session.user.email) || "");
    return loadDashboard();
  }

  function showLogin(message) {
    show(appView, false);
    show(loginView, true);
    show(authError, Boolean(message));
    authError.textContent = message || "";
  }

  document.getElementById("login-form").addEventListener("submit", function (event) {
    event.preventDefault();
    show(authError, false);
    client.auth
      .signInWithPassword({
        email: document.getElementById("email").value,
        password: document.getElementById("password").value,
      })
      .then(function (result) {
        if (result.error) throw result.error;
      })
      .catch(function (error) {
        showLogin(error.message || "Sign in failed.");
      });
  });

  function oauth(provider) {
    client.auth
      .signInWithOAuth({
        provider: provider,
        options: { redirectTo: window.location.origin + "/admin/" },
      })
      .then(function (result) {
        if (result.error) throw result.error;
      })
      .catch(function (error) {
        showLogin(error.message || "Sign in failed.");
      });
  }

  document.getElementById("google-btn").addEventListener("click", function () {
    oauth("google");
  });
  document.getElementById("github-btn").addEventListener("click", function () {
    oauth("github");
  });
  document.getElementById("sign-out").addEventListener("click", function () {
    selectedUserId = "";
    loadedUsers = [];
    client.auth.signOut();
  });
  document.getElementById("reload").addEventListener("click", function () {
    loadDashboard();
  });
  if (userFilter) {
    userFilter.addEventListener("change", renderUsers);
  }
  if (userSearch) {
    userSearch.addEventListener("input", renderUsers);
  }

  client.auth.onAuthStateChange(function (_event, session) {
    if (!session) {
      showLogin("");
      return;
    }
    showApp(session).catch(function (error) {
      if (String(error && error.code).indexOf("not_admin") !== -1) {
        client.auth.signOut();
        showLogin("This account is not an admin.");
      }
    });
  });
})();
