(function () {
  "use strict";

  var cfg = window.ROOTLIZE_SUPABASE || {};
  var createClient = window.supabase && window.supabase.createClient;
  if (!createClient || !cfg.url || !cfg.publishableKey) {
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

  var loginView = document.getElementById("login-view");
  var appView = document.getElementById("app-view");
  var authError = document.getElementById("auth-error");
  var appError = document.getElementById("app-error");

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

  function renderOverview(data, githubCount) {
    var lp = (data && data.lp) || {};
    var downloads = (data && data.downloads) || {};
    var users = (data && data.users) || {};
    var apiCost = (data && data.api_cost) || {};
    var tutorial = (data && data.tutorial) || {};
    var categories = apiCost.by_category || {};

    setText("kpi-visitors", String(lp.unique_visitors || 0));
    setText("kpi-pageviews", (lp.page_views || 0) + " page views");
    setText("kpi-downloads", String(downloads.clicks || 0));
    setText(
      "kpi-github-downloads",
      githubCount == null ? "CTA clicks" : "GitHub assets: " + githubCount
    );
    setText("kpi-users", String(users.total || 0));
    setText(
      "kpi-users-sub",
      "Today " + (users.today || 0) + " · 7 days " + (users.last_7_days || 0)
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

  function renderUsers(users) {
    var body = document.getElementById("users-body");
    body.innerHTML = "";
    if (!users || !users.length) {
      body.innerHTML =
        '<tr><td colspan="5" class="muted">No users yet.</td></tr>';
      return;
    }
    users.forEach(function (user) {
      var tr = document.createElement("tr");
      tr.dataset.userId = user.user_id;
      if (user.user_id === selectedUserId) tr.className = "is-selected";
      tr.innerHTML =
        "<td>" +
        escapeHtml(user.email || user.user_id) +
        "</td><td>" +
        escapeHtml(formatTime(user.signup_at)) +
        "</td><td>" +
        escapeHtml(formatUsd(user.api_cost_usd_micros)) +
        "</td><td>" +
        (user.tutorial_completed
          ? '<span class="badge badge-ok">Completed</span>'
          : '<span class="badge badge-muted">Not completed</span>') +
        "</td><td>" +
        escapeHtml(formatTime(user.last_event_at)) +
        "</td>";
      tr.addEventListener("click", function () {
        selectedUserId = user.user_id;
        Array.prototype.forEach.call(body.querySelectorAll("tr"), function (row) {
          row.classList.toggle("is-selected", row === tr);
        });
        loadHistory(user);
      });
      body.appendChild(tr);
    });
  }

  function escapeHtml(value) {
    return String(value || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function renderHistory(payload) {
    var list = document.getElementById("history-list");
    var events = (payload && payload.events) || [];
    setText(
      "history-user",
      (payload && payload.email) || (payload && payload.user_id) || ""
    );
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
      label.textContent = api.eventLabel(event.event_name);
      item.appendChild(time);
      item.appendChild(label);
      list.appendChild(item);
    });
  }

  function loadHistory(user) {
    api
      .getUserActivity(user.user_id)
      .then(renderHistory)
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
      api.getGithubDownloadCount(),
    ])
      .then(function (results) {
        var overview = results[0] || {};
        if (results[2]) overview.api_cost = results[2];
        renderOverview(overview, results[3]);
        renderUsers(results[1] || []);
        if (selectedUserId) {
          var match = (results[1] || []).filter(function (user) {
            return user.user_id === selectedUserId;
          })[0];
          if (match) loadHistory(match);
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
    client.auth.signOut();
  });
  document.getElementById("reload").addEventListener("click", function () {
    loadDashboard();
  });

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
