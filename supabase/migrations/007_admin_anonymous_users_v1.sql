-- Operator admin: Anonymous Auth + Prototype quota display.
-- Replace admin read RPCs only. Does not change entitlements, usage
-- ledgers, plan_defaults amounts, new-user trigger, or devices schema.
-- Identity stays auth.users.id. Installation IDs are devices.device_id.
-- Anonymous type uses auth.users.is_anonymous, not client metadata.
-- Apply after 005_admin_analytics_v1.sql and 006_prototype_anonymous_plan_v1.sql.

create or replace function public.admin_get_overview()
returns jsonb
language plpgsql
stable
security definer
set search_path = public
as $$
declare
  day_start timestamptz;
  unique_visitors bigint;
  page_views bigint;
  download_clicks bigint;
  user_total bigint;
  user_today bigint;
  user_last_7_days bigint;
  user_anonymous bigint;
  user_account bigint;
  user_prototype bigint;
  user_used_ai bigint;
  user_ai_limit bigint;
  api_total bigint;
  api_today bigint;
  vision_micros bigint;
  meaning_micros bigint;
  other_micros bigint;
  tutorial_started bigint;
  tutorial_completed bigint;
begin
  perform public._admin_require();
  day_start := public._admin_utc_day_start();

  select
    count(distinct visitor_id) filter (where event_name = 'page_view'),
    count(*) filter (where event_name = 'page_view'),
    count(*) filter (where event_name = 'download_click')
  into unique_visitors, page_views, download_clicks
  from public.website_analytics;

  select
    count(*),
    count(*) filter (where u.created_at >= day_start),
    count(*) filter (where u.created_at >= (timezone('utc', now()) - interval '7 days')),
    count(*) filter (where coalesce(u.is_anonymous, false)),
    count(*) filter (where not coalesce(u.is_anonymous, false)),
    count(*) filter (where e.plan = 'prototype'),
    count(*) filter (where coalesce(life.used_micros, 0) > 0),
    count(*) filter (
      where e.user_id is not null
        and case
          when coalesce(e.ai_lifetime_hard_cap_micros, 0) <= 0 then true
          else (coalesce(life.used_micros, 0) + coalesce(life.reserved_micros, 0))
            >= e.ai_lifetime_hard_cap_micros
        end
    )
  into
    user_total, user_today, user_last_7_days,
    user_anonymous, user_account, user_prototype,
    user_used_ai, user_ai_limit
  from auth.users u
  left join public.entitlements e on e.user_id = u.id
  left join public.ai_usage_lifetime life on life.user_id = u.id;

  select coalesce(sum(cost_usd_micros), 0)
  into api_total
  from public.ai_usage_events
  where status = 'finalized';

  select coalesce(sum(cost_usd_micros), 0)
  into api_today
  from public.ai_usage_events
  where status = 'finalized' and occurred_at >= day_start;

  select
    coalesce(sum(cost_usd_micros) filter (where operation = 'facts_generate'), 0),
    coalesce(sum(cost_usd_micros) filter (where operation = 'meaning_search'), 0),
    coalesce(sum(cost_usd_micros) filter (
      where operation is distinct from 'facts_generate'
        and operation is distinct from 'meaning_search'
    ), 0)
  into vision_micros, meaning_micros, other_micros
  from public.ai_usage_events
  where status = 'finalized';

  select count(distinct user_id)
  into tutorial_started
  from public.prototype_analytics
  where event_name = 'onboarding_started' and user_id is not null;

  select count(distinct user_id)
  into tutorial_completed
  from public.prototype_analytics
  where event_name = 'tutorial_completed' and user_id is not null;

  return jsonb_build_object(
    'lp', jsonb_build_object(
      'unique_visitors', coalesce(unique_visitors, 0),
      'page_views', coalesce(page_views, 0)
    ),
    'downloads', jsonb_build_object(
      'clicks', coalesce(download_clicks, 0)
    ),
    'users', jsonb_build_object(
      'total', coalesce(user_total, 0),
      'today', coalesce(user_today, 0),
      'last_7_days', coalesce(user_last_7_days, 0),
      'anonymous', coalesce(user_anonymous, 0),
      'account', coalesce(user_account, 0),
      'prototype', coalesce(user_prototype, 0),
      'used_ai', coalesce(user_used_ai, 0),
      'ai_limit_reached', coalesce(user_ai_limit, 0)
    ),
    'api_cost', jsonb_build_object(
      'total_usd_micros', coalesce(api_total, 0),
      'today_usd_micros', coalesce(api_today, 0),
      'by_category', jsonb_build_object(
        'vision_usd_micros', coalesce(vision_micros, 0),
        'meaning_search_usd_micros', coalesce(meaning_micros, 0),
        'other_usd_micros', coalesce(other_micros, 0)
      )
    ),
    'tutorial', jsonb_build_object(
      'started', coalesce(tutorial_started, 0),
      'completed', coalesce(tutorial_completed, 0),
      'completion_rate', case
        when coalesce(tutorial_started, 0) <= 0 then 0
        else round(
          (coalesce(tutorial_completed, 0)::numeric * 100)
          / tutorial_started
        , 1)
      end
    )
  );
end;
$$;

create or replace function public.admin_get_users()
returns jsonb
language plpgsql
stable
security definer
set search_path = public
as $$
begin
  perform public._admin_require();
  return coalesce(
    (
      select jsonb_agg(to_jsonb(item) order by item.signup_at desc)
      from (
        select
          u.id as user_id,
          u.email::text as email,
          coalesce(u.is_anonymous, false) as is_anonymous,
          u.created_at as signup_at,
          u.last_sign_in_at,
          coalesce(e.plan, '') as plan,
          coalesce(e.account_status, '') as account_status,
          coalesce(e.ai_allowed, false) as ai_allowed,
          coalesce(e.ai_monthly_budget_micros, pd.ai_monthly_budget_micros, 0)
            as ai_monthly_budget_micros,
          coalesce(e.ai_onboarding_budget_micros, pd.ai_onboarding_budget_micros, 0)
            as ai_onboarding_budget_micros,
          coalesce(e.ai_lifetime_hard_cap_micros, pd.ai_lifetime_hard_cap_micros, 0)
            as ai_hard_cap_micros,
          coalesce(life.used_micros, 0) as ai_used_micros,
          coalesce(life.reserved_micros, 0) as ai_reserved_micros,
          greatest(
            0,
            coalesce(e.ai_lifetime_hard_cap_micros, pd.ai_lifetime_hard_cap_micros, 0)
              - coalesce(life.used_micros, 0)
              - coalesce(life.reserved_micros, 0)
          ) as ai_remaining_micros,
          case
            when e.user_id is null then false
            when coalesce(e.ai_lifetime_hard_cap_micros, 0) <= 0 then true
            else (coalesce(life.used_micros, 0) + coalesce(life.reserved_micros, 0))
              >= e.ai_lifetime_hard_cap_micros
          end as ai_limit_reached,
          coalesce(cost.total_micros, 0) as api_cost_usd_micros,
          last_ai.occurred_at as ai_last_at,
          (completed.user_id is not null) as tutorial_completed,
          last_event.occurred_at as last_event_at,
          last_device.last_seen_at as device_last_seen_at,
          coalesce(dev.devices, '[]'::jsonb) as devices
        from auth.users u
        left join public.entitlements e on e.user_id = u.id
        left join public.plan_defaults pd on pd.plan = e.plan
        left join public.ai_usage_lifetime life on life.user_id = u.id
        left join (
          select user_id, sum(cost_usd_micros)::bigint as total_micros
          from public.ai_usage_events
          where status = 'finalized'
          group by user_id
        ) cost on cost.user_id = u.id
        left join (
          select user_id, max(occurred_at) as occurred_at
          from public.ai_usage_events
          group by user_id
        ) last_ai on last_ai.user_id = u.id
        left join (
          select distinct user_id
          from public.prototype_analytics
          where event_name = 'tutorial_completed' and user_id is not null
        ) completed on completed.user_id = u.id
        left join (
          select user_id, max(occurred_at) as occurred_at
          from public.prototype_analytics
          where user_id is not null
          group by user_id
        ) last_event on last_event.user_id = u.id
        left join (
          select user_id, max(last_seen_at) as last_seen_at
          from public.devices
          group by user_id
        ) last_device on last_device.user_id = u.id
        left join (
          select
            d.user_id,
            jsonb_agg(
              jsonb_build_object(
                'device_id', d.device_id,
                'device_name', d.device_name,
                'platform', d.platform,
                'last_seen_at', d.last_seen_at
              )
              order by d.last_seen_at desc
            ) as devices
          from public.devices d
          group by d.user_id
        ) dev on dev.user_id = u.id
      ) item
    ),
    '[]'::jsonb
  );
end;
$$;

create or replace function public.admin_get_user_activity(p_user_id uuid)
returns jsonb
language plpgsql
stable
security definer
set search_path = public
as $$
declare
  email text;
  is_anonymous boolean;
  signup_at timestamptz;
  last_sign_in_at timestamptz;
  plan text;
  account_status text;
  ai_allowed boolean;
  ai_monthly bigint;
  ai_onboarding bigint;
  ai_hard_cap bigint;
  ai_used bigint;
  ai_reserved bigint;
  ai_last_at timestamptz;
  devices jsonb;
begin
  perform public._admin_require();
  if p_user_id is null then
    raise exception 'invalid_user';
  end if;

  select
    u.email::text,
    coalesce(u.is_anonymous, false),
    u.created_at,
    u.last_sign_in_at
  into email, is_anonymous, signup_at, last_sign_in_at
  from auth.users u
  where u.id = p_user_id;
  if not found then
    raise exception 'user_not_found';
  end if;

  select
    e.plan,
    e.account_status,
    e.ai_allowed,
    coalesce(e.ai_monthly_budget_micros, pd.ai_monthly_budget_micros, 0),
    coalesce(e.ai_onboarding_budget_micros, pd.ai_onboarding_budget_micros, 0),
    coalesce(e.ai_lifetime_hard_cap_micros, pd.ai_lifetime_hard_cap_micros, 0)
  into plan, account_status, ai_allowed, ai_monthly, ai_onboarding, ai_hard_cap
  from public.entitlements e
  left join public.plan_defaults pd on pd.plan = e.plan
  where e.user_id = p_user_id;

  select
    coalesce(life.used_micros, 0),
    coalesce(life.reserved_micros, 0)
  into ai_used, ai_reserved
  from public.ai_usage_lifetime life
  where life.user_id = p_user_id;
  ai_used := coalesce(ai_used, 0);
  ai_reserved := coalesce(ai_reserved, 0);
  ai_monthly := coalesce(ai_monthly, 0);
  ai_onboarding := coalesce(ai_onboarding, 0);
  ai_hard_cap := coalesce(ai_hard_cap, 0);

  select max(occurred_at)
  into ai_last_at
  from public.ai_usage_events
  where user_id = p_user_id;

  select coalesce(
    jsonb_agg(
      jsonb_build_object(
        'device_id', d.device_id,
        'device_name', d.device_name,
        'platform', d.platform,
        'last_seen_at', d.last_seen_at
      )
      order by d.last_seen_at desc
    ),
    '[]'::jsonb
  )
  into devices
  from public.devices d
  where d.user_id = p_user_id;

  return jsonb_build_object(
    'user_id', p_user_id,
    'email', email,
    'is_anonymous', coalesce(is_anonymous, false),
    'signup_at', signup_at,
    'last_sign_in_at', last_sign_in_at,
    'plan', coalesce(plan, ''),
    'account_status', coalesce(account_status, ''),
    'ai_allowed', coalesce(ai_allowed, false),
    'ai_monthly_budget_micros', ai_monthly,
    'ai_onboarding_budget_micros', ai_onboarding,
    'ai_hard_cap_micros', ai_hard_cap,
    'ai_used_micros', ai_used,
    'ai_reserved_micros', ai_reserved,
    'ai_remaining_micros', greatest(0, ai_hard_cap - ai_used - ai_reserved),
    'ai_limit_reached', case
      when plan is null then false
      when ai_hard_cap <= 0 then true
      else (ai_used + ai_reserved) >= ai_hard_cap
    end,
    'ai_last_at', ai_last_at,
    'devices', coalesce(devices, '[]'::jsonb),
    'events', coalesce(
      (
        select jsonb_agg(jsonb_build_object(
          'event_name', recent.event_name,
          'occurred_at', recent.occurred_at
        ) order by recent.occurred_at)
        from (
          select event_name, occurred_at
          from (
            select 'signup'::text as event_name, signup_at as occurred_at
            union all
            select a.event_name, a.occurred_at
            from public.prototype_analytics a
            where a.user_id = p_user_id
          ) all_events
          order by occurred_at desc
          limit 500
        ) recent
      ),
      '[]'::jsonb
    )
  );
end;
$$;

create or replace function public.admin_get_api_usage()
returns jsonb
language plpgsql
stable
security definer
set search_path = public
as $$
declare
  day_start timestamptz;
  api_total bigint;
  api_today bigint;
  vision_micros bigint;
  meaning_micros bigint;
  other_micros bigint;
begin
  perform public._admin_require();
  day_start := public._admin_utc_day_start();

  select coalesce(sum(cost_usd_micros), 0)
  into api_total
  from public.ai_usage_events
  where status = 'finalized';

  select coalesce(sum(cost_usd_micros), 0)
  into api_today
  from public.ai_usage_events
  where status = 'finalized' and occurred_at >= day_start;

  select
    coalesce(sum(cost_usd_micros) filter (where operation = 'facts_generate'), 0),
    coalesce(sum(cost_usd_micros) filter (where operation = 'meaning_search'), 0),
    coalesce(sum(cost_usd_micros) filter (
      where operation is distinct from 'facts_generate'
        and operation is distinct from 'meaning_search'
    ), 0)
  into vision_micros, meaning_micros, other_micros
  from public.ai_usage_events
  where status = 'finalized';

  return jsonb_build_object(
    'total_usd_micros', coalesce(api_total, 0),
    'today_usd_micros', coalesce(api_today, 0),
    'by_category', jsonb_build_object(
      'vision_usd_micros', coalesce(vision_micros, 0),
      'meaning_search_usd_micros', coalesce(meaning_micros, 0),
      'other_usd_micros', coalesce(other_micros, 0)
    ),
    'by_user', coalesce(
      (
        select jsonb_agg(to_jsonb(item) order by item.api_cost_usd_micros desc)
        from (
          select
            e.user_id,
            u.email::text as email,
            coalesce(u.is_anonymous, false) as is_anonymous,
            coalesce(ent.plan, '') as plan,
            sum(e.cost_usd_micros)::bigint as api_cost_usd_micros
          from public.ai_usage_events e
          join auth.users u on u.id = e.user_id
          left join public.entitlements ent on ent.user_id = e.user_id
          where e.status = 'finalized'
          group by e.user_id, u.email, u.is_anonymous, ent.plan
        ) item
      ),
      '[]'::jsonb
    )
  );
end;
$$;

revoke all on function public.admin_get_overview() from public, anon;
revoke all on function public.admin_get_users() from public, anon;
revoke all on function public.admin_get_user_activity(uuid) from public, anon;
revoke all on function public.admin_get_api_usage() from public, anon;

grant execute on function public.admin_get_overview() to authenticated;
grant execute on function public.admin_get_users() to authenticated;
grant execute on function public.admin_get_user_activity(uuid) to authenticated;
grant execute on function public.admin_get_api_usage() to authenticated;
