"""Admin / website analytics contracts. No live Supabase calls."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent
MIGRATION = ROOT / "supabase" / "migrations" / "005_admin_analytics_v1.sql"
ANALYTICS_JS = ROOT / "website" / "js" / "analytics.js"
ADMIN_API = ROOT / "website" / "admin" / "api.js"
ADMIN_APP = ROOT / "website" / "admin" / "app.js"
WEBSITE = ROOT / "website"


def test_admin_rpcs_require_server_side_admin() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")
    for name in (
        "admin_get_overview",
        "admin_get_users",
        "admin_get_user_activity",
        "admin_get_api_usage",
    ):
        assert f"function public.{name}" in sql
        start = sql.index(f"function public.{name}")
        chunk = sql[start : start + 800]
        assert "perform public._admin_require();" in chunk
    assert "grant execute on function public.admin_get_overview() to authenticated;" in sql
    assert "grant execute on function public.admin_get_overview() to anon;" not in sql
    assert "grant select on public.website_analytics" not in sql.lower()
    assert "grant select on public.admin_users" not in sql.lower()


def test_website_analytics_opt_out_and_allowed_events() -> None:
    text = ANALYTICS_JS.read_text(encoding="utf-8")
    assert 'OPT_OUT_KEY = "rootlize_analytics_opt_out"' in text
    assert "lp_visit" in text
    assert "page_view" in text
    assert "download_click" in text
    assert "finger" not in text.lower()
    assert "ip address" not in text.lower()
    assert "user-agent" not in text.lower()


def test_admin_ui_uses_rpc_layer_only() -> None:
    api = ADMIN_API.read_text(encoding="utf-8")
    app = ADMIN_APP.read_text(encoding="utf-8")
    assert "admin_get_overview" in api
    assert "admin_get_users" in api
    assert "admin_get_user_activity" in api
    assert "admin_get_api_usage" in api
    assert ".from(" not in api
    assert "prototype_analytics" not in app
    assert "ai_usage_events" not in app
    assert "auth.users" not in app


def test_website_and_admin_do_not_ship_service_role() -> None:
    for path in WEBSITE.rglob("*"):
        if path.suffix.lower() not in {".js", ".html", ".css"}:
            continue
        text = path.read_text(encoding="utf-8")
        assert "service_role" not in text
        assert "SERVICE_ROLE" not in text
        assert '"role":"service_role"' not in text
        assert "role=service_role" not in text
