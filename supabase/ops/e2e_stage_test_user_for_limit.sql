-- Live E2E: tighten the SAME test user's hard cap after 1+ successful AI requests
-- so the next Ask AI reservation is rejected before the Provider call.
--
-- Changes only:
--   public.entitlements.ai_lifetime_hard_cap_micros  for that user
--   public.entitlements.updated_at                   for that user
--
-- Does not change used_micros, reserved_micros, events, other users, or
-- plan_defaults. Does not delete any row.
--
-- Why this exists:
--   Ask AI meaning_search reserves 10000 micros ($0.01). Actual finalize
--   cost is usually much smaller, so a $0.05 cap alone will not reach the
--   limit without many Provider calls. This script lowers that user's hard
--   cap to sit just at (or just under) current committed usage.
--
-- stage_mode:
--   'limit_reached'   hard_cap = used + reserved
--                     remaining = 0. Account shows limit reached.
--                     Next request is rejected before Provider.
--   'below_estimate'  hard_cap = used + reserved + 5000
--                     remaining = $0.005 < $0.01 reservation.
--                     Proxy reserve fails; Account may not yet say
--                     "limit reached" until you re-run with limit_reached.
--
-- Run only after a successful AI request (used+reserved must be > 0).
-- Edit the email (and optionally stage_mode), then run once.

drop table if exists e2e_target;
create temporary table e2e_target (
  email text primary key,
  stage_mode text not null
);
insert into e2e_target (email, stage_mode)
values ('REPLACE_WITH_TEST_USER_EMAIL', 'limit_reached');

do $$
declare
  test_email text;
  stage_mode text;
  test_user_id uuid;
  match_count integer;
  used_micros bigint;
  reserved_micros bigint;
  committed bigint;
  new_hard_cap bigint;
begin
  select t.email, t.stage_mode into test_email, stage_mode from e2e_target t;
  if test_email is null
     or btrim(test_email) = ''
     or test_email = 'REPLACE_WITH_TEST_USER_EMAIL' then
    raise exception 'Set e2e_target.email to the live test user email before running.';
  end if;
  if stage_mode not in ('limit_reached', 'below_estimate') then
    raise exception 'stage_mode must be limit_reached or below_estimate.';
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

  select
    coalesce(l.used_micros, 0),
    coalesce(l.reserved_micros, 0)
  into used_micros, reserved_micros
  from public.ai_usage_lifetime l
  where l.user_id = test_user_id;

  committed := coalesce(used_micros, 0) + coalesce(reserved_micros, 0);
  if committed <= 0 then
    raise exception
      'Abort: % has used+reserved = 0. Do one successful AI request first, then stage.',
      test_email;
  end if;

  if stage_mode = 'below_estimate' then
    -- remaining 5000 micros ($0.005) < meaning_search estimate 10000.
    new_hard_cap := committed + 5000;
  else
    -- remaining 0. limit_reached = true. Does not invent usage.
    new_hard_cap := committed;
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

  raise notice
    'Staged % mode=% hard_cap=% used=% reserved=% (usage rows unchanged).',
    test_email, stage_mode, new_hard_cap, coalesce(used_micros, 0),
    coalesce(reserved_micros, 0);
end $$;

select
  u.email,
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
  (coalesce(l.used_micros, 0) + coalesce(l.reserved_micros, 0))
    >= e.ai_lifetime_hard_cap_micros as limit_reached
from e2e_target t
join auth.users u on lower(u.email) = lower(t.email)
join public.entitlements e on e.user_id = u.id
left join public.ai_usage_lifetime l on l.user_id = u.id;
