-- Capixe AI Budget / Usage v1.
-- Amounts are integer USD micros (1 USD = 1_000_000 micros). Never float.
-- Final Free / Next / Pro prices are not decided. Change amounts in
-- plan_defaults / entitlements only. Desktop clients must not hardcode them.
--
-- Apply after 001_auth_v1.sql. Desktop clients use the publishable key only.
-- Reservation / finalize / release go through SECURITY DEFINER RPCs that
-- read auth.uid(). Clients must not pass user_id.

-- Safe testable default when a plan_defaults row is missing.
-- $0.25 = 250000 micros. Not a published price.

create table if not exists public.plan_defaults (
  plan text primary key,
  ai_monthly_budget_micros bigint not null check (ai_monthly_budget_micros >= 0),
  ai_allowed boolean not null default true
);

insert into public.plan_defaults (plan, ai_monthly_budget_micros, ai_allowed)
values
  ('free', 250000, true),
  ('next', 250000, true),
  ('pro', 250000, true)
on conflict (plan) do nothing;

alter table public.entitlements
  add column if not exists ai_monthly_budget_micros bigint;

update public.entitlements e
set ai_monthly_budget_micros = coalesce(
  e.ai_monthly_budget_micros,
  (select d.ai_monthly_budget_micros from public.plan_defaults d where d.plan = e.plan),
  250000
)
where e.ai_monthly_budget_micros is null;

alter table public.entitlements
  alter column ai_monthly_budget_micros set default 250000;

alter table public.entitlements
  alter column ai_monthly_budget_micros set not null;

alter table public.entitlements
  drop constraint if exists entitlements_budget_nonnegative;

alter table public.entitlements
  add constraint entitlements_budget_nonnegative
  check (ai_monthly_budget_micros >= 0);

-- Usage event log. Do not store query text, paths, filenames, OCR, facts,
-- embeddings, API keys, or tokens.
create table if not exists public.ai_usage_events (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users (id) on delete cascade,
  operation text not null,
  provider text not null default '',
  model text not null default '',
  cost_usd_micros bigint not null default 0,
  reserved_micros bigint not null default 0,
  actual_micros bigint,
  status text not null default 'reserved'
    check (status in ('reserved', 'finalized', 'released')),
  request_id text not null default '',
  occurred_at timestamptz not null default now()
);

create index if not exists ai_usage_events_user_occurred_idx
  on public.ai_usage_events (user_id, occurred_at desc);

create table if not exists public.ai_usage_periods (
  user_id uuid not null references auth.users (id) on delete cascade,
  period_start date not null,
  period_end date not null,
  budget_micros bigint not null,
  used_micros bigint not null default 0,
  reserved_micros bigint not null default 0,
  primary key (user_id, period_start),
  check (period_end > period_start),
  check (used_micros >= 0),
  check (reserved_micros >= 0),
  check (budget_micros >= 0)
);

alter table public.plan_defaults enable row level security;
alter table public.ai_usage_events enable row level security;
alter table public.ai_usage_periods enable row level security;

drop policy if exists ai_usage_events_select_own on public.ai_usage_events;
create policy ai_usage_events_select_own on public.ai_usage_events
  for select to authenticated
  using (auth.uid() = user_id);

drop policy if exists ai_usage_periods_select_own on public.ai_usage_periods;
create policy ai_usage_periods_select_own on public.ai_usage_periods
  for select to authenticated
  using (auth.uid() = user_id);

-- No insert / update / delete policies for authenticated on usage or plan_defaults.
-- entitlements already has select-only for authenticated (001).

create or replace function public.handle_new_capixe_user()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
declare
  default_budget bigint;
begin
  insert into public.profiles (user_id, display_name)
  values (new.id, coalesce(new.raw_user_meta_data->>'full_name', split_part(new.email, '@', 1), ''))
  on conflict (user_id) do nothing;

  select ai_monthly_budget_micros into default_budget
  from public.plan_defaults
  where plan = 'free';
  default_budget := coalesce(default_budget, 250000);

  insert into public.entitlements (
    user_id, plan, account_status, ai_allowed, ai_monthly_budget_micros
  )
  values (new.id, 'free', 'active', true, default_budget)
  on conflict (user_id) do nothing;
  return new;
end;
$$;

create or replace function public._ai_current_period_bounds()
returns table (period_start date, period_end date)
language sql
stable
set search_path = public
as $$
  select
    (date_trunc('month', timezone('utc', now())))::date,
    (date_trunc('month', timezone('utc', now())) + interval '1 month')::date;
$$;

create or replace function public._ai_lock_current_period(p_user_id uuid, p_budget_micros bigint)
returns public.ai_usage_periods
language plpgsql
security definer
set search_path = public
as $$
declare
  bounds record;
  period public.ai_usage_periods;
begin
  select * into bounds from public._ai_current_period_bounds();
  insert into public.ai_usage_periods (
    user_id, period_start, period_end, budget_micros, used_micros, reserved_micros
  )
  values (
    p_user_id, bounds.period_start, bounds.period_end, greatest(p_budget_micros, 0), 0, 0
  )
  on conflict (user_id, period_start) do nothing;

  select * into period
  from public.ai_usage_periods
  where user_id = p_user_id and period_start = bounds.period_start
  for update;

  update public.ai_usage_periods
  set budget_micros = greatest(p_budget_micros, 0)
  where user_id = p_user_id and period_start = bounds.period_start
  returning * into period;
  return period;
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
  estimated bigint;
  event_id uuid;
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
  if ent.ai_monthly_budget_micros <= 0 then
    raise exception 'ai_budget_exceeded' using hint = (
      select period_end::text from public._ai_current_period_bounds()
    );
  end if;

  period := public._ai_lock_current_period(uid, ent.ai_monthly_budget_micros);
  if period.used_micros + period.reserved_micros + estimated > ent.ai_monthly_budget_micros then
    raise exception 'ai_budget_exceeded' using hint = period.period_end::text;
  end if;

  update public.ai_usage_periods
  set reserved_micros = reserved_micros + estimated
  where user_id = uid and period_start = period.period_start;

  insert into public.ai_usage_events (
    user_id, operation, provider, model, reserved_micros, cost_usd_micros,
    status, request_id
  )
  values (
    uid,
    coalesce(nullif(p_operation, ''), 'other'),
    coalesce(p_provider, ''),
    coalesce(p_model, ''),
    estimated,
    0,
    'reserved',
    coalesce(p_request_id, '')
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
  actual bigint;
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

  period := public._ai_lock_current_period(uid, (
    select ai_monthly_budget_micros from public.entitlements where user_id = uid
  ));

  update public.ai_usage_periods
  set
    reserved_micros = greatest(reserved_micros - ev.reserved_micros, 0),
    used_micros = used_micros + actual
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

  period := public._ai_lock_current_period(uid, (
    select ai_monthly_budget_micros from public.entitlements where user_id = uid
  ));

  update public.ai_usage_periods
  set reserved_micros = greatest(reserved_micros - ev.reserved_micros, 0)
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
  period public.ai_usage_periods;
  committed bigint;
  budget bigint;
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

  period := public._ai_lock_current_period(uid, ent.ai_monthly_budget_micros);
  budget := greatest(ent.ai_monthly_budget_micros, 0);
  committed := greatest(period.used_micros, 0) + greatest(period.reserved_micros, 0);
  if budget <= 0 then
    used_pct := 100;
    remaining_pct := 0;
    reached := true;
  else
    used_pct := least(100, (committed::numeric * 100) / budget);
    remaining_pct := greatest(0, 100 - used_pct);
    reached := committed >= budget;
  end if;
  if (not ent.ai_allowed) or (ent.account_status is distinct from 'active') then
    reached := true;
  end if;

  return jsonb_build_object(
    'used_percent', used_pct,
    'remaining_percent', remaining_pct,
    'reset_at', period.period_end,
    'limit_reached', reached,
    'budget_micros', budget,
    'used_micros', period.used_micros,
    'reserved_micros', period.reserved_micros,
    'plan', ent.plan,
    'account_status', ent.account_status,
    'ai_allowed', ent.ai_allowed
  );
end;
$$;

revoke all on public.plan_defaults from anon, authenticated;
revoke all on public.ai_usage_events from anon, authenticated;
revoke all on public.ai_usage_periods from anon, authenticated;
grant select on public.ai_usage_events, public.ai_usage_periods to authenticated;
grant select on public.entitlements to authenticated;

revoke all on function public._ai_current_period_bounds() from public, anon, authenticated;
revoke all on function public._ai_lock_current_period(uuid, bigint) from public, anon, authenticated;
revoke all on function public.reserve_ai_budget(bigint, text, text, text, text) from public, anon;
revoke all on function public.finalize_ai_usage(uuid, bigint) from public, anon;
revoke all on function public.release_ai_reservation(uuid) from public, anon;
revoke all on function public.get_ai_usage_status() from public, anon;

grant execute on function public.reserve_ai_budget(bigint, text, text, text, text) to authenticated;
grant execute on function public.finalize_ai_usage(uuid, bigint) to authenticated;
grant execute on function public.release_ai_reservation(uuid) to authenticated;
grant execute on function public.get_ai_usage_status() to authenticated;
