-- Read-only. Confirms 006_prototype_anonymous_plan_v1.sql is on this project.
-- Safe to run on live. Does not write.
-- Does not change free / next / pro amounts.

select
  (select count(*) from public.plan_defaults where plan = 'prototype') = 1
    as prototype_plan_exists,
  (select ai_lifetime_hard_cap_micros from public.plan_defaults where plan = 'prototype')
    = 1250000 as prototype_hard_cap_is_1_25,
  (select ai_onboarding_budget_micros from public.plan_defaults where plan = 'prototype')
    = 1250000 as prototype_onboarding_is_1_25,
  (select ai_monthly_budget_micros from public.plan_defaults where plan = 'prototype')
    = 250000 as prototype_monthly_is_0_25,
  (select ai_lifetime_hard_cap_micros from public.plan_defaults where plan = 'free')
    = 1250000 as free_hard_cap_unchanged,
  (select ai_monthly_budget_micros from public.plan_defaults where plan = 'free')
    = 250000 as free_monthly_unchanged;

select
  pg_get_functiondef(p.oid) like '%prototype%' as new_user_trigger_uses_prototype_plan
from pg_proc p
join pg_namespace n on n.oid = p.pronamespace
where n.nspname = 'public'
  and p.proname = 'handle_new_capixe_user';
