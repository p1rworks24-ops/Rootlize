-- Read-only live inspect for the Public Prototype AI budget E2E.
-- Safe to run on live. Does not write production rows. Does not delete.
--
-- Edit the email in the insert, then run the whole script.

drop table if exists e2e_target;
create temporary table e2e_target (email text primary key);
insert into e2e_target (email) values ('REPLACE_WITH_TEST_USER_EMAIL');

select
  t.email as requested_email,
  count(u.id) as matching_auth_users
from e2e_target t
left join auth.users u on lower(u.email) = lower(t.email)
group by t.email;

with target as (
  select u.id as user_id, u.email
  from auth.users u
  join e2e_target t on lower(u.email) = lower(t.email)
)
select
  'plan_defaults' as row_kind,
  d.plan,
  d.ai_lifetime_hard_cap_micros as hard_cap_micros,
  d.ai_onboarding_budget_micros as onboarding_micros,
  d.ai_monthly_budget_micros as monthly_micros,
  null::bigint as used_micros,
  null::bigint as reserved_micros,
  null::text as email
from public.plan_defaults d
union all
select
  'test_user_entitlements',
  e.plan,
  e.ai_lifetime_hard_cap_micros,
  e.ai_onboarding_budget_micros,
  e.ai_monthly_budget_micros,
  null,
  null,
  t.email
from public.entitlements e
join target t on t.user_id = e.user_id
union all
select
  'test_user_lifetime',
  e.plan,
  e.ai_lifetime_hard_cap_micros,
  e.ai_onboarding_budget_micros,
  e.ai_monthly_budget_micros,
  coalesce(l.used_micros, 0),
  coalesce(l.reserved_micros, 0),
  t.email
from target t
left join public.entitlements e on e.user_id = t.user_id
left join public.ai_usage_lifetime l on l.user_id = t.user_id
order by row_kind;

-- Remaining vs Ask AI reservation. meaning_search estimate is 10000 micros ($0.01).
with target as (
  select u.id as user_id, u.email
  from auth.users u
  join e2e_target t on lower(u.email) = lower(t.email)
)
select
  t.email,
  e.ai_lifetime_hard_cap_micros as hard_cap_micros,
  coalesce(l.used_micros, 0) as used_micros,
  coalesce(l.reserved_micros, 0) as reserved_micros,
  greatest(
    e.ai_lifetime_hard_cap_micros
      - coalesce(l.used_micros, 0)
      - coalesce(l.reserved_micros, 0),
    0
  ) as remaining_micros,
  10000 as meaning_search_estimate_micros,
  greatest(
    e.ai_lifetime_hard_cap_micros
      - coalesce(l.used_micros, 0)
      - coalesce(l.reserved_micros, 0),
    0
  ) < 10000 as next_meaning_search_would_reject,
  (coalesce(l.used_micros, 0) + coalesce(l.reserved_micros, 0))
    >= e.ai_lifetime_hard_cap_micros as limit_reached
from target t
left join public.entitlements e on e.user_id = t.user_id
left join public.ai_usage_lifetime l on l.user_id = t.user_id;

-- Other users must stay on the official $1.25 hard cap during this E2E.
with target as (
  select u.id as user_id
  from auth.users u
  join e2e_target t on lower(u.email) = lower(t.email)
)
select
  count(*) filter (
    where e.user_id not in (select user_id from target)
      and e.ai_lifetime_hard_cap_micros is distinct from 1250000
  ) as other_users_not_on_official_hard_cap,
  count(*) filter (
    where e.user_id in (select user_id from target)
      and e.ai_lifetime_hard_cap_micros = 50000
  ) as test_user_on_temporary_0_05,
  count(*) as entitlement_rows
from public.entitlements e;
