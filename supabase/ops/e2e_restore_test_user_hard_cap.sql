-- Live E2E restore: return ONE test user to the official $1.25 hard cap.
--
-- Changes only:
--   public.entitlements.ai_lifetime_hard_cap_micros  for that user
--   public.entitlements.updated_at                   for that user
--
-- New hard cap is copied from plan_defaults for that user's plan
-- (official free value is 1250000). plan_defaults itself is not updated.
--
-- Does not change:
--   used_micros / reserved_micros (real E2E spend, usually a few cents)
--   ai_usage_events / ai_usage_periods
--   other users
--
-- Does not delete any production row.
-- After restore, remaining is $1.25 minus the tiny live E2E spend.
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
  official_hard_cap bigint;
  user_plan text;
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

  select plan into user_plan
  from public.entitlements
  where user_id = test_user_id;
  if user_plan is null then
    raise exception 'No entitlements row for %', test_email;
  end if;

  select d.ai_lifetime_hard_cap_micros into official_hard_cap
  from public.plan_defaults d
  where d.plan = user_plan;
  official_hard_cap := coalesce(official_hard_cap, 1250000);

  if official_hard_cap is distinct from 1250000 then
    raise exception
      'Abort: plan_defaults.% hard cap is %, expected official 1250000.',
      user_plan, official_hard_cap;
  end if;

  update public.entitlements
  set
    ai_lifetime_hard_cap_micros = official_hard_cap,
    updated_at = now()
  where user_id = test_user_id
    and user_id in (
      select id from auth.users where lower(email) = lower(test_email)
    );

  if not found then
    raise exception 'Update changed 0 rows for %', test_email;
  end if;

  raise notice 'Restored % hard cap to % micros ($1.25). used/reserved/events kept.',
    test_email, official_hard_cap;
end $$;

select
  u.email,
  e.plan,
  e.ai_lifetime_hard_cap_micros as hard_cap_micros,
  coalesce(l.used_micros, 0) as used_micros,
  coalesce(l.reserved_micros, 0) as reserved_micros,
  greatest(
    e.ai_lifetime_hard_cap_micros
      - coalesce(l.used_micros, 0)
      - coalesce(l.reserved_micros, 0),
    0
  ) as remaining_micros
from e2e_target t
join auth.users u on lower(u.email) = lower(t.email)
join public.entitlements e on e.user_id = u.id
left join public.ai_usage_lifetime l on l.user_id = u.id;

select
  plan,
  ai_lifetime_hard_cap_micros
from public.plan_defaults
order by plan;

select
  count(*) filter (where e.ai_lifetime_hard_cap_micros is distinct from 1250000)
    as users_not_on_official_hard_cap
from public.entitlements e;
