/**
 * Admin data access. UI calls these methods only.
 * Queries go through SECURITY DEFINER RPCs; tables are never queried here.
 */
(function (root) {
  "use strict";

  var EVENT_LABELS = {
    signup: "Signup",
    onboarding_started: "Tutorial Started",
    onboarding_completed: "Getting Started Completed",
    onboarding_skipped: "Getting Started Skipped",
    tutorial_completed: "Tutorial Completed",
    ai_tutorial_started: "Ask AI Tutorial Started",
    ai_tutorial_completed: "Ask AI Tutorial Completed",
    ai_tutorial_skipped: "Ask AI Tutorial Skipped",
    automation_tutorial_started: "Automation Tutorial Started",
    automation_tutorial_completed: "Automation Tutorial Completed",
    automation_tutorial_skipped: "Automation Tutorial Skipped",
    basic_search_completed: "Basic Search",
    meaning_search_completed: "Meaning Search",
    tag_added: "Tag Added",
    workflow_saved: "Workflow Saved",
    workflow_run: "Workflow Run",
    folder_selected: "Folder Selected",
    ai_preparation_started: "AI Preparation Started",
    ask_ai_consent_shown: "Ask AI Consent Shown",
    ask_ai_consent_accepted: "Ask AI Consent Accepted",
    ask_ai_consent_cancelled: "Ask AI Consent Cancelled",
    feedback_shown: "Feedback Shown",
    feedback_submitted: "Feedback Submitted",
    feedback_dismissed: "Feedback Dismissed",
  };

  var GITHUB_RELEASES =
    "https://api.github.com/repos/p1rworks24-ops/Rootlize/releases?per_page=10";

  function AdminApi(client) {
    this.client = client;
  }

  AdminApi.prototype._rpc = function (name, args) {
    return this.client.rpc(name, args || {}).then(function (result) {
      if (result.error) {
        var error = new Error(result.error.message || name + " failed");
        error.code = result.error.message || "";
        error.status = result.error.code || "";
        throw error;
      }
      return result.data;
    });
  };

  AdminApi.prototype.getOverview = function () {
    return this._rpc("admin_get_overview");
  };

  AdminApi.prototype.getUsers = function () {
    return this._rpc("admin_get_users");
  };

  AdminApi.prototype.getUserActivity = function (userId) {
    return this._rpc("admin_get_user_activity", { p_user_id: userId });
  };

  AdminApi.prototype.getApiUsage = function () {
    return this._rpc("admin_get_api_usage");
  };

  AdminApi.prototype.eventLabel = function (eventName) {
    var name = String(eventName || "");
    if (EVENT_LABELS[name]) return EVENT_LABELS[name];
    return name.replace(/_/g, " ");
  };

  AdminApi.prototype.getGithubDownloadCount = function () {
    if (typeof fetch !== "function") {
      return Promise.resolve(null);
    }
    return fetch(GITHUB_RELEASES, {
      headers: { Accept: "application/vnd.github+json" },
    })
      .then(function (response) {
        if (!response.ok) return null;
        return response.json();
      })
      .then(function (releases) {
        if (!Array.isArray(releases)) return null;
        var total = 0;
        releases.forEach(function (release) {
          if (!release || release.draft || !Array.isArray(release.assets)) return;
          release.assets.forEach(function (asset) {
            total += Number(asset && asset.download_count) || 0;
          });
        });
        return total;
      })
      .catch(function () {
        return null;
      });
  };

  root.RootlizeAdminApi = AdminApi;
})(window);
