# Capixe Auth v1 (Supabase)

Desktop Capixe uses **Supabase Auth** for account identity only. Images, paths, OCR, facts, embeddings, tags, and search history stay on the PC.

## Put in the desktop client

These are publishable. Env vars override `resources/auth-source.json`. If an env key looks like a provider secret (`sk-...`) or `service_role`, Capixe skips it and uses the file key instead. It never loads that secret into the client.

* `CAPIXE_SUPABASE_URL` — project URL, e.g. `https://xyz.supabase.co`
* `CAPIXE_SUPABASE_PUBLISHABLE_KEY` — anon / publishable key (`sb_publishable_...` or JWT `role=anon`)

Local unpublished file (gitignored; preferred over the empty template):

`resources/auth-source.local.json`

Official packaged Prototype build (`tools/build_official_prototype.py`) bakes only these publishable fields into `dist\Capixe\Capixe.exe`. That path is the only human verification EXE.

`resources/auth-source.json`:

```json
{
  "supabase_url": "https://YOUR_PROJECT.supabase.co",
  "publishable_key": "YOUR_ANON_OR_PUBLISHABLE_KEY"
}
```

## Never put in the desktop client / EXE

* `service_role` key
* Stripe secrets
* OpenAI / provider secrets
* OAuth client secrets

## Dashboard

1. Run `supabase/migrations/001_auth_v1.sql`, then `002_ai_budget_v1.sql`, then `003_prototype_feedback_v1.sql` for Prototype feedback / funnel events, then `004_prototype_ai_budget_v1.sql` for the Public Prototype AI hard cap, then `005_admin_analytics_v1.sql` for operator admin analytics, then `006_prototype_anonymous_plan_v1.sql` for anonymous Prototype plan defaults (does not change `free` / `next` / `pro`).
2. Auth → Providers: Email, Google, GitHub. For the public Prototype (D-042), also enable **Anonymous sign-ins**. Packaged Rootlize uses this for AI budget identity without a Sign-in gate. Turn it off when `AUTH_REQUIRED` is restored to True if you no longer need guest AI.
3. Auth → URL configuration. Add redirect:

   `http://127.0.0.1:47831/auth/callback`

   For the operator admin page, also add:

   `https://rootlize.com/admin/`

   Local admin testing:

   `http://localhost:8080/admin/`

   Capixe opens the **default browser** and completes OAuth with PKCE on this loopback URL (D-022). Do **not** put a client `state` on `/auth/v1/authorize`; GoTrue owns the Google/GitHub `flow_state` UUID. A client token in `state` becomes `400: OAuth state parameter is invalid` on `/callback`.
4. Optional: enable email confirmations. The app shows “Check your email…” when signup has no session.
5. Do **not** implement custom “same email auto-merge”. Use Supabase identity linking only if you enable it in the project. Capixe treats `auth.users.id` as `user_id` (D-023).

## What the client may write

* `profiles.display_name` for the signed-in user
* `devices` rows for this PC (`device_id` is local and survives sign-out)
* `prototype_feedback` / `prototype_analytics` (session, event name, feedback answers, app version). Never image, path, query, facts, or OCR.

`prototype_feedback` columns for Table Editor review:

* `user_id`
* `prototype_session_id`
* `completed_at`
* `app_version`
* `feedback_version`
* `most_useful`
* `would_use`
* `easier_than_current`
* `confusing_text`
* `willingness_to_pay`

Local fallback if cloud write fails: `%LOCALAPPDATA%\Capixe\prototype-feedback.jsonl`

## What the client may only read

* `entitlements.plan`, `account_status`, `ai_allowed`, `ai_monthly_budget_micros`, `ai_onboarding_budget_micros`, `ai_lifetime_hard_cap_micros`
* own `ai_usage_periods` / `ai_usage_events` / `ai_usage_lifetime` rows

The client must not write plan, account_status, ai_allowed, budget, used, or reserved. Reservation / finalize / release / usage status go through RPCs:

* `reserve_ai_budget`
* `finalize_ai_usage`
* `release_ai_reservation`
* `get_ai_usage_status`

Those functions use `auth.uid()`. Do not accept a client-supplied `user_id`.

Packaged Prototype (D-042) still sends `Authorization: Bearer <access token>`. The token is a GoTrue **anonymous** user JWT when Sign-in is not required. Usage is keyed by that `auth.uid()`, not by a client `installation_id` header. Local `%LOCALAPPDATA%\Capixe\device.json` stores the opaque installation UUID and upserts `devices`. Anonymous users get `plan='prototype'` from `006_prototype_anonymous_plan_v1.sql`. Change Prototype amounts in that `plan_defaults` row only.

Public Prototype amounts live in `plan_defaults` / `entitlements`: onboarding $1.25, regular $0.25 / UTC month, lifetime hard cap $1.25 / user. `get_ai_usage_status` reports used % against the hard cap, not the monthly bucket. Final Free / Next / Pro prices are not decided and must not appear in the public UI. User-facing plan name is Prototype while the internal plan ID stays `free` for signed-in accounts and `prototype` for anonymous Prototype users. Change amounts in the database only.

Local `%LOCALAPPDATA%\Capixe\ai-usage.sqlite3` remains debug telemetry. Cloud usage is the enforceable budget.

## Operator admin analytics

Static GitHub Pages cannot authorize admin reads. The admin UI at `https://rootlize.com/admin/` signs in with Supabase Auth (anon / publishable key only) and calls SECURITY DEFINER RPCs:

* `admin_get_overview`
* `admin_get_users`
* `admin_get_user_activity`
* `admin_get_api_usage`

Those RPCs call `_admin_require()`, which checks `public.admin_users`. Ordinary signed-in Rootlize users receive `not_admin` and no rows. Do not put a service_role key in the website, EXE, or admin JS.

After applying `005_admin_analytics_v1.sql`, grant yourself access in the SQL editor (use your real operator email):

```sql
insert into public.admin_users (user_id)
select id from auth.users
where email = 'YOUR_OPERATOR_EMAIL'
on conflict (user_id) do nothing;
```

Confirm with `supabase/ops/e2e_verify_005_admin_analytics.sql`. Expected: `admin_users` / `website_analytics` present; anon can insert website events but cannot select them; authenticated can execute the admin RPCs (the RPC still rejects non-admins).

Landing-page events (`lp_visit`, `page_view`, `download_click`) go to `website_analytics`. Operator browsers can opt out without deleting visitor rows:

* `https://rootlize.com/?analytics=off` — stop sending
* `https://rootlize.com/?analytics=on` — resume sending

The flag is `localStorage.rootlize_analytics_opt_out = true`. Console: `__rootlizeAnalytics.optOut()`, `.optIn()`, `.status()`.

## AI Provider Proxy v1

Product AI (`facts_generate` / `meaning_search` / `act_plan`) goes through one Edge Function. The desktop client does not call OpenAI.

```text
supabase functions deploy ai-proxy
```

Local serve:

```text
supabase functions serve ai-proxy --no-verify-jwt
```

`--no-verify-jwt` is for local harnesses only. The function still calls `auth.getUser()` and rejects missing/invalid tokens. Packaged Capixe always sends `Authorization: Bearer <access token>` (signed-in or Prototype anonymous).

### Required secrets

Set values in the Supabase project. Do not put values in git, EXE, or this README.

* `OPENAI_API_KEY` — Provider secret. Required for live proxy.
* `SUPABASE_URL` / `SUPABASE_ANON_KEY` — injected by the platform. Do not replace with `service_role` in the desktop client.

Optional Function env (not client env):

* `CAPIXE_AI_MODEL` — must stay on the server allowlist (`gpt-5.4-mini` in v1)
* `CAPIXE_AI_ESTIMATE_MICROS_FACTS_GENERATE`
* `CAPIXE_AI_ESTIMATE_MICROS_MEANING_SEARCH`
* `CAPIXE_AI_ESTIMATE_MICROS_ACT_PLAN`

```text
supabase secrets set OPENAI_API_KEY=...
```

### Required migrations

Apply `001_auth_v1.sql`, `002_ai_budget_v1.sql`, `004_prototype_ai_budget_v1.sql`, then `006_prototype_anonymous_plan_v1.sql` for anonymous Prototype users. The proxy calls the existing RPCs with the **user JWT**, so `auth.uid()` stays the identity. It does not accept a client `user_id`. Anonymous JWTs are valid `authenticated` tokens. Edge Function code does not need a redeploy for Prototype Sign-in bypass; enable Anonymous sign-ins in the Auth dashboard.

Live E2E of the usage-limit UI must not burn the official $1.25. Lower one test user's hard cap only, then restore it. Procedures and SQL: `docs/PROTOTYPE_AI_BUDGET_LIVE_E2E.md` and `supabase/ops/e2e_*.sql`. Do not change `plan_defaults` or other users for that test.

### Request

```json
{
  "operation": "meaning_search",
  "payload": {},
  "request_id": "optional-idempotency-key"
}
```

Client must not send `user_id`, `plan`, `budget`, `model`, `endpoint`, `headers`, or `api_key`. Those fields are rejected.

### Desktop client

Production default is the proxy. Direct OpenAI is only `CAPIXE_AI_DIRECT_PROVIDER=1` in a non-packaged process. Public `Capixe.exe` never uses a local Provider secret.
