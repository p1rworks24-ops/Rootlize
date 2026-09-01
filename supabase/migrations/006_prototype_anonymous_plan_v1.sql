-- Prototype anonymous users get a dedicated plan row.
-- Do not change free / next / pro amounts here (those stay D-041 / 004).
-- Anonymous identity is still auth.users.id (GoTrue anonymous JWT).
-- Clients must not pass user_id. Installation UUID lives in devices + user_metadata.
-- Apply after 004_prototype_ai_budget_v1.sql.
-- Dashboard: Authentication → Providers → enable Anonymous sign-ins.

insert into public.plan_defaults (
  plan,
  ai_monthly_budget_micros,
  ai_allowed,
  ai_onboarding_budget_micros,
  ai_lifetime_hard_cap_micros
)
values (
  'prototype',
  250000,
  true,
  1250000,
  1250000
)
on conflict (plan) do nothing;

create or replace function public.handle_new_capixe_user()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
declare
  plan_name text;
  default_budget bigint;
  default_onboarding bigint;
  default_hard_cap bigint;
begin
  plan_name := case
    when coalesce(new.is_anonymous, false) then 'prototype'
    else 'free'
  end;

  insert into public.profiles (user_id, display_name)
  values (
    new.id,
    coalesce(new.raw_user_meta_data->>'full_name', split_part(new.email, '@', 1), '')
  )
  on conflict (user_id) do nothing;

  select
    ai_monthly_budget_micros,
    ai_onboarding_budget_micros,
    ai_lifetime_hard_cap_micros
  into default_budget, default_onboarding, default_hard_cap
  from public.plan_defaults
  where plan = plan_name;

  if default_budget is null then
    select
      ai_monthly_budget_micros,
      ai_onboarding_budget_micros,
      ai_lifetime_hard_cap_micros
    into default_budget, default_onboarding, default_hard_cap
    from public.plan_defaults
    where plan = 'free';
  end if;

  default_budget := coalesce(default_budget, 250000);
  default_onboarding := coalesce(default_onboarding, 1250000);
  default_hard_cap := coalesce(default_hard_cap, 1250000);

  insert into public.entitlements (
    user_id, plan, account_status, ai_allowed,
    ai_monthly_budget_micros, ai_onboarding_budget_micros, ai_lifetime_hard_cap_micros
  )
  values (
    new.id, plan_name, 'active', true,
    default_budget, default_onboarding, default_hard_cap
  )
  on conflict (user_id) do nothing;

  insert into public.ai_usage_lifetime (user_id)
  values (new.id)
  on conflict (user_id) do nothing;
  return new;
end;
$$;
