-- Live E2E: lower ONE test user's Prototype lifetime hard cap to $0.05.
--
-- Changes only:
--   public.entitlements.ai_lifetime_hard_cap_micros  for that user
--   public.entitlements.updated_at                   for that user
--
-- Does not change:
--   plan_defaults (official $1.25 / $0.25 stay)
--   other users' entitlements
--   ai_usage_lifetime.used_micros / reserved_micros
--   ai_usage_periods / ai_usage_events
--
-- Does not delete any production row.
--
-- $0.05 = 50000 USD micros. Ask AI meaning_search reserves 10000 ($0.01).
-- facts_generate reserves 50000 ($0.05). Use a folder that already has facts
-- so the first Ask AI is meaning_search only.
--
-- Edit the email in the insert, then run the whole script once.

drop table if exists e2e_target;
create temporary table e2e_target (email text primary key);
insert into e2e_target (email) values ('REPLACE_WITH_TEST_USER_EMAIL');

do $$
declare
  test_email text;
  test_user_id uuid;
  match_count integer;
  new_hard_cap constant bigint := 50000;
begin
  select email into test_email from e2e_target;
  if test_email is null
     or btrim(test_email) = ''
     or test_email = 'REPLACE_WITH_TEST_USER_EMAIL' then
    raise exception 'Set e2e_target.email to the live test user email before running.';
  end if;

  select count(*) into match_count
  from auth.users
  where lower(email) = lower(test_email);
  if match_count <> 1 then
    raise exception 'Expected exactly 1 auth.users row for %, found %',
      test_email, match_count;
  end if;

  select id into test_user_id
  from auth.users
  where lower(email) = lower(test_email);

  if not exists (
    select 1 from public.entitlements where user_id = test_user_id
  ) then
    raise exception 'No entitlements row for %. Apply 004 first and sign in once.',
      test_email;
  end if;

  if exists (
    select 1
    from public.plan_defaults
    where plan = 'free'
      and ai_lifetime_hard_cap_micros is distinct from 1250000
  ) then
    raise exception 'Abort: plan_defaults.free hard cap is not the official 1250000.';
  end if;

  update public.entitlements
  set
    ai_lifetime_hard_cap_micros = new_hard_cap,
    updated_at = now()
  where user_id = test_user_id
    and user_id in (
      select id from auth.users where lower(email) = lower(test_email)
    );

  if not found then
    raise exception 'Update changed 0 rows for %', test_email;
  end if;

  raise notice 'Set % hard cap to % micros ($0.05). used/reserved unchanged.',
    test_email, new_hard_cap;
end $$;

select
  u.email,
  e.plan,
  e.ai_lifetime_hard_cap_micros as hard_cap_micros,
  e.ai_onboarding_budget_micros as onboarding_micros,
  e.ai_monthly_budget_micros as monthly_micros,
  coalesce(l.used_micros, 0) as used_micros,
  coalesce(l.reserved_micros, 0) as reserved_micros,
  e.updated_at
from e2e_target t
join auth.users u on lower(u.email) = lower(t.email)
join public.entitlements e on e.user_id = u.id
left join public.ai_usage_lifetime l on l.user_id = u.id;

select
  plan,
  ai_lifetime_hard_cap_micros
from public.plan_defaults
order by plan;
