-- Read-only. Confirms 004_prototype_ai_budget_v1.sql is on this project.
-- Safe to run on live. Does not write.
-- Apply 004 only after 001_auth_v1.sql and 002_ai_budget_v1.sql.

select
  to_regclass('public.plan_defaults') as plan_defaults,
  to_regclass('public.entitlements') as entitlements,
  to_regclass('public.ai_usage_periods') as ai_usage_periods,
  to_regclass('public.ai_usage_events') as ai_usage_events,
  to_regclass('public.ai_usage_lifetime') as ai_usage_lifetime;

select
  column_name,
  data_type
from information_schema.columns
where table_schema = 'public'
  and table_name in ('plan_defaults', 'entitlements')
  and column_name in (
    'ai_monthly_budget_micros',
    'ai_onboarding_budget_micros',
    'ai_lifetime_hard_cap_micros'
  )
order by table_name, column_name;

select
  plan,
  ai_monthly_budget_micros,
  ai_onboarding_budget_micros,
  ai_lifetime_hard_cap_micros,
  ai_allowed
from public.plan_defaults
order by plan;

select
  p.proname as function_name
from pg_proc p
join pg_namespace n on n.oid = p.pronamespace
where n.nspname = 'public'
  and p.proname in (
    'reserve_ai_budget',
    'finalize_ai_usage',
    'release_ai_reservation',
    'get_ai_usage_status'
  )
order by p.proname;

-- Official Public Prototype amounts. Do not change these for E2E.
-- free hard cap / onboarding must stay 1250000 ($1.25).
-- free monthly must stay 250000 ($0.25).
select
  (select ai_lifetime_hard_cap_micros from public.plan_defaults where plan = 'free')
    = 1250000 as free_hard_cap_is_1_25,
  (select ai_onboarding_budget_micros from public.plan_defaults where plan = 'free')
    = 1250000 as free_onboarding_is_1_25,
  (select ai_monthly_budget_micros from public.plan_defaults where plan = 'free')
    = 250000 as free_monthly_is_0_25,
  to_regclass('public.ai_usage_lifetime') is not null as lifetime_table_exists;
