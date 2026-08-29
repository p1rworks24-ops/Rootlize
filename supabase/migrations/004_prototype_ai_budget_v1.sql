-- Public Prototype AI budget.
-- Onboarding $1.25, regular $0.25 / UTC month, lifetime hard cap $1.25 / user.
-- Amounts are integer USD micros (1 USD = 1_000_000). Never float.
-- Hard cap is the enforceable total. Monthly regular reset cannot exceed it.
-- Apply after 002_ai_budget_v1.sql. Desktop clients must not hardcode amounts.
-- Reservation / finalize / release still use auth.uid(). Clients must not
-- pass user_id, plan, budget, or bucket.

alter table public.plan_defaults
  add column if not exists ai_onboarding_budget_micros bigint;

alter table public.plan_defaults
  add column if not exists ai_lifetime_hard_cap_micros bigint;

update public.plan_defaults
set
  ai_onboarding_budget_micros = coalesce(ai_onboarding_budget_micros, 1250000),
  ai_lifetime_hard_cap_micros = coalesce(ai_lifetime_hard_cap_micros, 1250000),
  ai_monthly_budget_micros = 250000;

alter table public.plan_defaults
  alter column ai_onboarding_budget_micros set default 1250000;

alter table public.plan_defaults
  alter column ai_lifetime_hard_cap_micros set default 1250000;

alter table public.plan_defaults
  alter column ai_onboarding_budget_micros set not null;

alter table public.plan_defaults
  alter column ai_lifetime_hard_cap_micros set not null;

alter table public.plan_defaults
  drop constraint if exists plan_defaults_onboarding_nonnegative;

alter table public.plan_defaults
  add constraint plan_defaults_onboarding_nonnegative
  check (ai_onboarding_budget_micros >= 0);

alter table public.plan_defaults
  drop constraint if exists plan_defaults_hard_cap_nonnegative;

alter table public.plan_defaults
  add constraint plan_defaults_hard_cap_nonnegative
  check (ai_lifetime_hard_cap_micros >= 0);

alter table public.entitlements
  add column if not exists ai_onboarding_budget_micros bigint;

alter table public.entitlements
  add column if not exists ai_lifetime_hard_cap_micros bigint;

update public.entitlements e
set
  ai_onboarding_budget_micros = coalesce(
    e.ai_onboarding_budget_micros,
    (select d.ai_onboarding_budget_micros from public.plan_defaults d where d.plan = e.plan),
    1250000
  ),
  ai_lifetime_hard_cap_micros = coalesce(
    e.ai_lifetime_hard_cap_micros,
    (select d.ai_lifetime_hard_cap_micros from public.plan_defaults d where d.plan = e.plan),
    1250000
  ),
  ai_monthly_budget_micros = coalesce(
    (select d.ai_monthly_budget_micros from public.plan_defaults d where d.plan = e.plan),
    250000
  );

alter table public.entitlements
  alter column ai_onboarding_budget_micros set default 1250000;

alter table public.entitlements
  alter column ai_lifetime_hard_cap_micros set default 1250000;

alter table public.entitlements
  alter column ai_onboarding_budget_micros set not null;

alter table public.entitlements
  alter column ai_lifetime_hard_cap_micros set not null;

alter table public.entitlements
  drop constraint if exists entitlements_onboarding_nonnegative;

alter table public.entitlements
  add constraint entitlements_onboarding_nonnegative
  check (ai_onboarding_budget_micros >= 0);

alter table public.entitlements
  drop constraint if exists entitlements_hard_cap_nonnegative;

alter table public.entitlements
  add constraint entitlements_hard_cap_nonnegative
  check (ai_lifetime_hard_cap_micros >= 0);

-- Lifetime + onboarding counters. Regular monthly usage stays on ai_usage_periods.
-- Do not store query text, paths, filenames, OCR, facts, embeddings, or keys.
create table if not exists public.ai_usage_lifetime (
  user_id uuid primary key references auth.users (id) on delete cascade,
  used_micros bigint not null default 0,
  reserved_micros bigint not null default 0,
  onboarding_used_micros bigint not null default 0,
  onboarding_reserved_micros bigint not null default 0,
  check (used_micros >= 0),
  check (reserved_micros >= 0),
  check (onboarding_used_micros >= 0),
  check (onboarding_reserved_micros >= 0)
);

alter table public.ai_usage_events
  add column if not exists onboarding_reserved_micros bigint not null default 0;

alter table public.ai_usage_events
  add column if not exists regular_reserved_micros bigint not null default 0;

alter table public.ai_usage_lifetime enable row level security;

drop policy if exists ai_usage_lifetime_select_own on public.ai_usage_lifetime;
create policy ai_usage_lifetime_select_own on public.ai_usage_lifetime
  for select to authenticated
  using (auth.uid() = user_id);

revoke all on public.ai_usage_lifetime from anon, authenticated;
grant select on public.ai_usage_lifetime to authenticated;

-- Historical monthly rows were the only usage ledger. Treat that spend as
-- onboarding first so lifetime hard cap stays accurate after this migration.
insert into public.ai_usage_lifetime (
  user_id, used_micros, reserved_micros, onboarding_used_micros, onboarding_reserved_micros
)
select
  e.user_id,
  coalesce(agg.used_micros, 0),
  coalesce(agg.reserved_micros, 0),
  least(coalesce(agg.used_micros, 0), e.ai_onboarding_budget_micros),
  0
from public.entitlements e
left join (
  select user_id,
    sum(used_micros)::bigint as used_micros,
    sum(reserved_micros)::bigint as reserved_micros
  from public.ai_usage_periods
  group by user_id
) agg on agg.user_id = e.user_id
on conflict (user_id) do nothing;

create or replace function public.handle_new_capixe_user()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
declare
  default_budget bigint;
  default_onboarding bigint;
  default_hard_cap bigint;
begin
  insert into public.profiles (user_id, display_name)
  values (new.id, coalesce(new.raw_user_meta_data->>'full_name', split_part(new.email, '@', 1), ''))
  on conflict (user_id) do nothing;

  select
    ai_monthly_budget_micros,
    ai_onboarding_budget_micros,
    ai_lifetime_hard_cap_micros
  into default_budget, default_onboarding, default_hard_cap
  from public.plan_defaults
  where plan = 'free';
  default_budget := coalesce(default_budget, 250000);
  default_onboarding := coalesce(default_onboarding, 1250000);
  default_hard_cap := coalesce(default_hard_cap, 1250000);

  insert into public.entitlements (
    user_id, plan, account_status, ai_allowed,
    ai_monthly_budget_micros, ai_onboarding_budget_micros, ai_lifetime_hard_cap_micros
  )
  values (
    new.id, 'free', 'active', true,
    default_budget, default_onboarding, default_hard_cap
  )
  on conflict (user_id) do nothing;

  insert into public.ai_usage_lifetime (user_id)
  values (new.id)
  on conflict (user_id) do nothing;
  return new;
end;
$$;

create or replace function public._ai_lock_lifetime(p_user_id uuid)
returns public.ai_usage_lifetime
language plpgsql
security definer
set search_path = public
as $$
declare
  lifetime public.ai_usage_lifetime;
begin
  insert into public.ai_usage_lifetime (user_id)
  values (p_user_id)
  on conflict (user_id) do nothing;

  select * into lifetime
  from public.ai_usage_lifetime
  where user_id = p_user_id
  for update;
  return lifetime;
end;
$$;

create or replace function public.reserve_ai_budget(
  p_estimated_cost_micros bigint,
  p_operation text,
  p_provider text default '',
  p_model text default '',
  p_request_id text default ''
)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  uid uuid := auth.uid();
  ent public.entitlements%rowtype;
  period public.ai_usage_periods;
  lifetime public.ai_usage_lifetime;
  estimated bigint;
  event_id uuid;
  hard_cap bigint;
  onboarding_budget bigint;
  monthly_budget bigint;
  lifetime_remaining bigint;
  onboarding_remaining bigint;
  regular_remaining bigint;
  available bigint;
  from_onboarding bigint;
  from_regular bigint;
begin
  if uid is null then
    raise exception 'ai_not_authenticated';
  end if;
  if p_estimated_cost_micros is null or p_estimated_cost_micros < 0 then
    raise exception 'ai_invalid_estimate';
  end if;
  estimated := p_estimated_cost_micros;

  select * into ent
  from public.entitlements
  where user_id = uid
  for update;
  if not found then
    raise exception 'ai_not_allowed';
  end if;
  if ent.account_status is distinct from 'active' then
    raise exception 'ai_account_inactive';
  end if;
  if not ent.ai_allowed then
    raise exception 'ai_not_allowed';
  end if;

  hard_cap := greatest(ent.ai_lifetime_hard_cap_micros, 0);
  onboarding_budget := greatest(ent.ai_onboarding_budget_micros, 0);
  monthly_budget := greatest(ent.ai_monthly_budget_micros, 0);
  if hard_cap <= 0 then
    raise exception 'ai_budget_exceeded';
  end if;

  lifetime := public._ai_lock_lifetime(uid);
  period := public._ai_lock_current_period(uid, monthly_budget);

  lifetime_remaining := hard_cap
    - greatest(lifetime.used_micros, 0)
    - greatest(lifetime.reserved_micros, 0);
  onboarding_remaining := onboarding_budget
    - greatest(lifetime.onboarding_used_micros, 0)
    - greatest(lifetime.onboarding_reserved_micros, 0);
  regular_remaining := monthly_budget
    - greatest(period.used_micros, 0)
    - greatest(period.reserved_micros, 0);
  if lifetime_remaining < 0 then
    lifetime_remaining := 0;
  end if;
  if onboarding_remaining < 0 then
    onboarding_remaining := 0;
  end if;
  if regular_remaining < 0 then
    regular_remaining := 0;
  end if;

  available := least(lifetime_remaining, onboarding_remaining + regular_remaining);
  if estimated > available then
    raise exception 'ai_budget_exceeded';
  end if;

  from_onboarding := least(estimated, onboarding_remaining);
  from_regular := estimated - from_onboarding;

  update public.ai_usage_lifetime
  set
    reserved_micros = reserved_micros + estimated,
    onboarding_reserved_micros = onboarding_reserved_micros + from_onboarding
  where user_id = uid;

  update public.ai_usage_periods
  set reserved_micros = reserved_micros + from_regular
  where user_id = uid and period_start = period.period_start;

  insert into public.ai_usage_events (
    user_id, operation, provider, model, reserved_micros, cost_usd_micros,
    status, request_id, onboarding_reserved_micros, regular_reserved_micros
  )
  values (
    uid,
    coalesce(nullif(p_operation, ''), 'other'),
    coalesce(p_provider, ''),
    coalesce(p_model, ''),
    estimated,
    0,
    'reserved',
    coalesce(p_request_id, ''),
    from_onboarding,
    from_regular
  )
  returning id into event_id;

  return jsonb_build_object(
    'reservation_id', event_id,
    'reserved_micros', estimated
  );
end;
$$;

create or replace function public.finalize_ai_usage(
  p_reservation_id uuid,
  p_actual_cost_micros bigint
)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  uid uuid := auth.uid();
  ev public.ai_usage_events%rowtype;
  period public.ai_usage_periods;
  lifetime public.ai_usage_lifetime;
  actual bigint;
  onboarding_actual bigint;
  regular_actual bigint;
begin
  if uid is null then
    raise exception 'ai_not_authenticated';
  end if;
  if p_reservation_id is null then
    raise exception 'ai_reservation_not_found';
  end if;

  select * into ev
  from public.ai_usage_events
  where id = p_reservation_id
  for update;
  if not found or ev.user_id is distinct from uid then
    raise exception 'ai_reservation_not_found';
  end if;
  if ev.status = 'finalized' then
    return jsonb_build_object(
      'status', 'finalized',
      'already', true,
      'reservation_id', ev.id,
      'actual_micros', ev.actual_micros
    );
  end if;
  if ev.status = 'released' then
    return jsonb_build_object(
      'status', 'released',
      'already', true,
      'reservation_id', ev.id
    );
  end if;

  actual := coalesce(p_actual_cost_micros, ev.reserved_micros);
  if actual < 0 then
    actual := ev.reserved_micros;
  end if;

  lifetime := public._ai_lock_lifetime(uid);
  period := public._ai_lock_current_period(uid, (
    select ai_monthly_budget_micros from public.entitlements where user_id = uid
  ));

  onboarding_actual := least(actual, greatest(ev.onboarding_reserved_micros, 0));
  regular_actual := actual - onboarding_actual;

  update public.ai_usage_lifetime
  set
    reserved_micros = greatest(reserved_micros - ev.reserved_micros, 0),
    onboarding_reserved_micros = greatest(
      onboarding_reserved_micros - ev.onboarding_reserved_micros, 0
    ),
    used_micros = used_micros + actual,
    onboarding_used_micros = onboarding_used_micros + onboarding_actual
  where user_id = uid;

  update public.ai_usage_periods
  set
    reserved_micros = greatest(reserved_micros - ev.regular_reserved_micros, 0),
    used_micros = used_micros + regular_actual
  where user_id = uid and period_start = period.period_start;

  update public.ai_usage_events
  set
    status = 'finalized',
    actual_micros = actual,
    cost_usd_micros = actual
  where id = ev.id;

  return jsonb_build_object(
    'status', 'finalized',
    'already', false,
    'reservation_id', ev.id,
    'actual_micros', actual
  );
end;
$$;

create or replace function public.release_ai_reservation(
  p_reservation_id uuid
)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  uid uuid := auth.uid();
  ev public.ai_usage_events%rowtype;
  period public.ai_usage_periods;
begin
  if uid is null then
    raise exception 'ai_not_authenticated';
  end if;
  if p_reservation_id is null then
    raise exception 'ai_reservation_not_found';
  end if;

  select * into ev
  from public.ai_usage_events
  where id = p_reservation_id
  for update;
  if not found or ev.user_id is distinct from uid then
    raise exception 'ai_reservation_not_found';
  end if;
  if ev.status = 'released' then
    return jsonb_build_object(
      'status', 'released',
      'already', true,
      'reservation_id', ev.id
    );
  end if;
  if ev.status = 'finalized' then
    return jsonb_build_object(
      'status', 'finalized',
      'already', true,
      'reservation_id', ev.id
    );
  end if;

  perform public._ai_lock_lifetime(uid);
  period := public._ai_lock_current_period(uid, (
    select ai_monthly_budget_micros from public.entitlements where user_id = uid
  ));

  update public.ai_usage_lifetime
  set
    reserved_micros = greatest(reserved_micros - ev.reserved_micros, 0),
    onboarding_reserved_micros = greatest(
      onboarding_reserved_micros - ev.onboarding_reserved_micros, 0
    )
  where user_id = uid;

  update public.ai_usage_periods
  set reserved_micros = greatest(reserved_micros - ev.regular_reserved_micros, 0)
  where user_id = uid and period_start = period.period_start;

  update public.ai_usage_events
  set status = 'released', cost_usd_micros = 0, actual_micros = 0
  where id = ev.id;

  return jsonb_build_object(
    'status', 'released',
    'already', false,
    'reservation_id', ev.id
  );
end;
$$;

create or replace function public.get_ai_usage_status()
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  uid uuid := auth.uid();
  ent public.entitlements%rowtype;
  lifetime public.ai_usage_lifetime;
  committed bigint;
  hard_cap bigint;
  used_pct numeric;
  remaining_pct numeric;
  reached boolean;
begin
  if uid is null then
    raise exception 'ai_not_authenticated';
  end if;

  select * into ent from public.entitlements where user_id = uid;
  if not found then
    raise exception 'ai_not_allowed';
  end if;

  lifetime := public._ai_lock_lifetime(uid);
  hard_cap := greatest(ent.ai_lifetime_hard_cap_micros, 0);
  committed := greatest(lifetime.used_micros, 0) + greatest(lifetime.reserved_micros, 0);
  if hard_cap <= 0 then
    used_pct := 100;
    remaining_pct := 0;
    reached := true;
  else
    used_pct := least(100, (committed::numeric * 100) / hard_cap);
    remaining_pct := greatest(0, 100 - used_pct);
    reached := committed >= hard_cap;
  end if;
  if (not ent.ai_allowed) or (ent.account_status is distinct from 'active') then
    reached := true;
  end if;

  return jsonb_build_object(
    'used_percent', used_pct,
    'remaining_percent', remaining_pct,
    'limit_reached', reached,
    'budget_micros', hard_cap,
    'used_micros', lifetime.used_micros,
    'reserved_micros', lifetime.reserved_micros,
    'hard_cap_micros', hard_cap,
    'plan', ent.plan,
    'plan_display', 'Prototype',
    'account_status', ent.account_status,
    'ai_allowed', ent.ai_allowed
  );
end;
$$;

revoke all on function public._ai_lock_lifetime(uuid) from public, anon, authenticated;
revoke all on function public.reserve_ai_budget(bigint, text, text, text, text) from public, anon;
revoke all on function public.finalize_ai_usage(uuid, bigint) from public, anon;
revoke all on function public.release_ai_reservation(uuid) from public, anon;
revoke all on function public.get_ai_usage_status() from public, anon;

grant execute on function public.reserve_ai_budget(bigint, text, text, text, text) to authenticated;
grant execute on function public.finalize_ai_usage(uuid, bigint) to authenticated;
grant execute on function public.release_ai_reservation(uuid) to authenticated;
grant execute on function public.get_ai_usage_status() to authenticated;
