"""Admin Anonymous / Prototype display contracts. No live Supabase writes."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MIGRATION = ROOT / "supabase" / "migrations" / "007_admin_anonymous_users_v1.sql"
ADMIN_HTML = ROOT / "website" / "admin" / "index.html"
ADMIN_APP = ROOT / "website" / "admin" / "app.js"
ADMIN_DISPLAY = ROOT / "website" / "admin" / "display.js"
ADMIN_API = ROOT / "website" / "admin" / "api.js"


def _sql() -> str:
    return MIGRATION.read_text(encoding="utf-8")


def test_admin_anonymous_sql_reads_auth_and_quota_not_client_metadata() -> None:
    sql = _sql()
    assert "u.is_anonymous" in sql
    assert "raw_user_meta_data" not in sql
    assert "installation_id" not in sql
    assert "ai_usage_lifetime" in sql
    assert "ai_lifetime_hard_cap_micros" in sql
    assert "public.devices" in sql
    assert "public.entitlements" in sql
    assert "public.plan_defaults" in sql
    assert "create or replace function public.handle_new_capixe_user" not in sql
    assert "reserve_ai_budget" not in sql
    assert "alter table public.entitlements" not in sql
    assert "alter table public.devices" not in sql
    assert "create table" not in sql.lower()
    assert "u.id as user_id" in sql
    assert "d.device_id" in sql
    assert "grant execute on function public.admin_get_users() to anon;" not in sql
    assert "filename" not in sql.lower()
    assert "image_facts" not in sql.lower()
    assert "1250000" not in sql
    assert "1.25" not in sql


def test_admin_anonymous_sql_does_not_sum_budget_buckets() -> None:
    sql = _sql()
    assert "ai_monthly_budget_micros + " not in sql.replace("\n", " ")
    assert "ai_onboarding_budget_micros +" not in sql
    assert "used_micros" in sql
    assert "ai_lifetime_hard_cap_micros" in sql
    users_fn = sql[sql.index("function public.admin_get_users()") :]
    users_fn = users_fn[: users_fn.index("function public.admin_get_user_activity")]
    assert "life.used_micros" in users_fn
    assert "e.ai_lifetime_hard_cap_micros" in users_fn
    assert "e.ai_monthly_budget_micros, pd.ai_monthly_budget_micros" in users_fn


def test_admin_overview_splits_guest_account_prototype() -> None:
    sql = _sql()
    overview = sql[sql.index("function public.admin_get_overview()") :]
    overview = overview[: overview.index("function public.admin_get_users()")]
    assert "'anonymous'" in overview
    assert "'account'" in overview
    assert "'prototype'" in overview
    assert "'used_ai'" in overview
    assert "'ai_limit_reached'" in overview
    assert "coalesce(u.is_anonymous, false)" in overview
    assert "e.plan = 'prototype'" in overview


def test_admin_activity_works_without_email() -> None:
    sql = _sql()
    activity = sql[sql.index("function public.admin_get_user_activity") :]
    assert "if p_user_id is null" in activity
    assert "where u.id = p_user_id" in activity
    assert "email is not null" not in activity
    assert "'is_anonymous'" in activity
    assert "'devices'" in activity
    assert "p_device_id" not in activity
    assert "p_installation" not in activity


def test_admin_ui_treats_anonymous_as_normal_guest() -> None:
    html = ADMIN_HTML.read_text(encoding="utf-8")
    app = ADMIN_APP.read_text(encoding="utf-8")
    display = ADMIN_DISPLAY.read_text(encoding="utf-8")
    assert "display.js" in html
    assert "Anonymous / Guest" in html
    assert "Installation ID" in html
    assert "User ID" not in html.split("Installations")[1]
    assert "Guest \\u00b7 " in display or "Guest \u00b7 " in display
    assert 'id === "prototype"' in display
    assert 'return "Prototype"' in display
    assert 'return "Free"' in display
    assert 'return "Next"' in display
    assert 'return "Pro"' in display
    assert "Active Guest" in display
    assert "AI limit reached" in display
    assert "Never used AI" in display
    assert "user.email || user.user_id" not in app
    assert "Unknown user" not in app
    assert "Unknown user" not in display
    assert "1250000" not in display
    assert "1.25" not in display
    assert "1.25" not in app
    assert "formatUsdPair" in app
    assert "user.user_id" in app
    assert "device.device_id" in app


def test_admin_ui_filters_exist() -> None:
    html = ADMIN_HTML.read_text(encoding="utf-8")
    display = ADMIN_DISPLAY.read_text(encoding="utf-8")
    assert 'value="all"' in html
    assert 'value="anonymous"' in html
    assert 'value="account"' in html
    assert 'value="prototype"' in html
    assert 'value="ai_limit"' in html
    assert "kpi-guests" in html
    assert "kpi-accounts" in html
    assert "matchesFilter" in display
    assert "matchesQuery" in display
    assert "compareUsers" in display


def _run_display_js(cases: list[dict]) -> list[dict]:
    node = shutil.which("node")
    assert node, "node is required to verify admin display helpers"
    harness = f"""
const fs = require('fs');
const vm = require('vm');
const sandbox = {{ window: {{}} }};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync({json.dumps(str(ADMIN_DISPLAY))}, 'utf8'), sandbox);
const d = sandbox.window.RootlizeAdminDisplay;
const cases = {json.dumps(cases)};
const out = cases.map((c) => ({{
  label: d.userLabel(c.user),
  type: d.userTypeLabel(c.user),
  plan: d.planLabel(c.user && c.user.plan),
  status: d.statusLabel(c.user),
  usage: d.formatUsdPair(c.user && c.user.ai_used_micros, c.user && c.user.ai_hard_cap_micros),
  filter: d.matchesFilter(c.user, c.filter),
  query: d.matchesQuery(c.user, c.query),
  sort: d.compareUsers(c.user, c.other || {{}}, 'email'),
}}));
process.stdout.write(JSON.stringify(out));
"""
    result = subprocess.run(
        [node, "-e", harness],
        check=True,
        capture_output=True,
        encoding="utf-8",
    )
    return json.loads(result.stdout)


def test_admin_display_cases_guest_account_usage_and_edges() -> None:
    guest_a = {
        "user_id": "3d55374c-aaaa-bbbb-cccc-ddddeeeeffff",
        "email": None,
        "is_anonymous": True,
        "plan": "prototype",
        "ai_used_micros": 420000,
        "ai_hard_cap_micros": 1250000,
        "ai_remaining_micros": 830000,
        "ai_limit_reached": False,
        "devices": [{"device_id": "11111111-2222-3333-4444-555555555555"}],
    }
    guest_b = {
        "user_id": "9f0c12ab-aaaa-bbbb-cccc-ddddeeeeffff",
        "email": None,
        "is_anonymous": True,
        "plan": "prototype",
        "ai_used_micros": 0,
        "ai_hard_cap_micros": 1250000,
        "ai_remaining_micros": 1250000,
        "ai_limit_reached": False,
        "devices": [],
    }
    guest_limit = {
        "user_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        "email": None,
        "is_anonymous": True,
        "plan": "prototype",
        "ai_used_micros": 1250000,
        "ai_hard_cap_micros": 1250000,
        "ai_remaining_micros": 0,
        "ai_limit_reached": True,
        "devices": [{"device_id": "aaaaaaaa-bbbb-cccc-dddd-ffffffffffff"}],
    }
    account = {
        "user_id": "bbbbbbbb-cccc-dddd-eeee-ffffffffffff",
        "email": "ops@example.com",
        "is_anonymous": False,
        "plan": "free",
        "ai_used_micros": 100000,
        "ai_hard_cap_micros": 1250000,
        "ai_remaining_micros": 1150000,
        "ai_limit_reached": False,
        "devices": [{"device_id": "dddddddd-eeee-ffff-aaaa-bbbbbbbbbbbb"}],
    }
    reused = dict(guest_a)
    reused["last_sign_in_at"] = "2026-09-01T10:00:00Z"

    results = _run_display_js(
        [
            {"user": guest_a, "filter": "anonymous", "query": "guest"},
            {"user": guest_b, "filter": "anonymous", "query": "9f0c12ab", "other": guest_a},
            {"user": guest_limit, "filter": "ai_limit", "query": ""},
            {"user": account, "filter": "account", "query": "ops@example.com", "other": guest_a},
            {"user": guest_a, "filter": "prototype", "query": "3d55374c"},
            {"user": account, "filter": "anonymous", "query": "guest"},
            {"user": guest_a, "filter": "account", "query": ""},
            {"user": reused, "filter": "all", "query": ""},
            {
                "user": {
                    "user_id": "3d55374c-aaaa-bbbb-cccc-ddddeeeeffff",
                    "email": None,
                },
                "filter": "all",
                "query": "",
            },
        ]
    )

    (
        a,
        b,
        limit,
        acc,
        proto,
        acc_as_guest,
        guest_as_account,
        reused_session,
        old_payload,
    ) = results

    assert a["label"] == "Guest \u00b7 3d55374c"
    assert a["type"] == "Anonymous"
    assert a["plan"] == "Prototype"
    assert a["status"] == "Active Guest"
    assert a["usage"] == "$0.42 / $1.25"
    assert a["filter"] is True
    assert a["query"] is True

    assert b["label"] == "Guest \u00b7 9f0c12ab"
    assert b["label"] != a["label"]
    assert b["status"] == "Never used AI"
    assert b["usage"] == "$0.00 / $1.25"
    assert b["query"] is True
    assert b["sort"] == 1 or b["sort"] == -1

    assert limit["status"] == "AI limit reached"
    assert limit["usage"] == "$1.25 / $1.25"
    assert limit["filter"] is True

    assert acc["label"] == "ops@example.com"
    assert acc["type"] == "Account"
    assert acc["plan"] == "Free"
    assert acc["status"] == "Account"
    assert acc["usage"] == "$0.10 / $1.25"
    assert acc["filter"] is True
    assert acc_as_guest["filter"] is False
    assert guest_as_account["filter"] is False
    assert proto["filter"] is True
    assert reused_session["label"] == a["label"]
    assert reused_session["type"] == "Anonymous"
    assert old_payload["label"] == "3d55374c-aaaa-bbbb-cccc-ddddeeeeffff"
    assert old_payload["type"] == "—"


def test_admin_activity_rpc_uses_auth_user_uuid() -> None:
    api = ADMIN_API.read_text(encoding="utf-8")
    app = ADMIN_APP.read_text(encoding="utf-8")
    assert '{ p_user_id: userId }' in api or "{ p_user_id: userId }" in api
    assert "getUserActivity(user.user_id)" in app
    assert "p_device_id" not in api
    assert "installation_id" not in api
    assert "installation_id" not in app
