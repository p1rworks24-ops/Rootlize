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
    app_launched: "App launched",
    session_started: "Session started",
    folder_added: "Folder added",
    search_completed: "Search completed",
    ai_request_completed: "AI request completed",
    workflow_created: "Workflow created",
    workflow_previewed: "Workflow previewed",
    workflow_executed: "Workflow executed",
    file_action_completed: "File action completed",
    account_created: "Account created",
    upgrade_viewed: "Upgrade viewed",
  };

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

  AdminApi.prototype.getProductUserDetail = function (userId) {
    return this._rpc("admin_get_product_user_detail", { p_user_id: userId });
  };

  AdminApi.prototype.getProductFunnel = function () {
    return this._rpc("admin_get_product_funnel");
  };

  AdminApi.prototype.eventLabel = function (eventName) {
    var name = String(eventName || "");
    if (EVENT_LABELS[name]) return EVENT_LABELS[name];
    return name.replace(/_/g, " ");
  };

  root.RootlizeAdminApi = AdminApi;
})(window);
