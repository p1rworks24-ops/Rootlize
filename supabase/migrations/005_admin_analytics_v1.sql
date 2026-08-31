-- Operator admin analytics.
-- Apply after 001_auth_v1.sql, 002_ai_budget_v1.sql, 003_prototype_feedback_v1.sql,
-- and 004_prototype_ai_budget_v1.sql.
--
-- Website events: anon insert only. No select for anon/authenticated.
-- Admin reads go through SECURITY DEFINER RPCs that check admin_users.
-- Desktop clients must not call these RPCs except from the operator admin UI.
-- Do not store query, path, filename, image, OCR, facts, tag names, or API keys.

create table if not exists public.admin_users (
  user_id uuid primary key references auth.users (id) on delete cascade,
  created_at timestamptz not null default now()
);

alter table public.admin_users enable row level security;
revoke all on public.admin_users from anon, authenticated;

create table if not exists public.website_analytics (
  id uuid primary key default gen_random_uuid(),
  visitor_id text not null,
  event_name text not null,
  occurred_at timestamptz not null default now(),
  constraint website_analytics_event_name_check
    check (event_name in ('lp_visit', 'page_view', 'download_click')),
  constraint website_analytics_visitor_id_check
    check (char_length(visitor_id) between 8 and 64)
);

create index if not exists website_analytics_event_occurred_idx
  on public.website_analytics (event_name, occurred_at);
create index if not exists website_analytics_visitor_idx
  on public.website_analytics (visitor_id);
create index if not exists prototype_analytics_user_occurred_idx
  on public.prototype_analytics (user_id, occurred_at desc);
create index if not exists prototype_analytics_event_user_idx
  on public.prototype_analytics (event_name, user_id)
  where user_id is not null;
create index if not exists ai_usage_events_status_occurred_idx
  on public.ai_usage_events (status, occurred_at);

alter table public.website_analytics enable row level security;

drop policy if exists website_analytics_insert_anon on public.website_analytics;
create policy website_analytics_insert_anon on public.website_analytics
  for insert to anon
  with check (
    event_name in ('lp_visit', 'page_view', 'download_click')
    and char_length(visitor_id) between 8 and 64
  );

revoke all on public.website_analytics from anon, authenticated;
grant insert on public.website_analytics to anon;

create or replace function public.is_rootlize_admin()
returns boolean
language sql
stable
security definer
set search_path = public
as $$
  select exists (
    select 1 from public.admin_users where user_id = auth.uid()
  );
$$;

revoke all on function public.is_rootlize_admin() from public, anon, authenticated;

create or replace function public._admin_require()
returns void
language plpgsql
stable
security definer
set search_path = public
as $$
begin
  if auth.uid() is null then
    raise exception 'not_authenticated';
  end if;
  if not public.is_rootlize_admin() then
    raise exception 'not_admin';
  end if;
end;
$$;

revoke all on function public._admin_require() from public, anon, authenticated;

create or replace function public._admin_utc_day_start()
returns timestamptz
language sql
stable
set search_path = public
as $$
  select date_trunc('day', timezone('utc', now())) at time zone 'utc';
$$;

revoke all on function public._admin_utc_day_start() from public, anon, authenticated;

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
    count(*) filter (where created_at >= day_start),
    count(*) filter (where created_at >= (timezone('utc', now()) - interval '7 days'))
  into user_total, user_today, user_last_7_days
  from auth.users;

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
      'last_7_days', coalesce(user_last_7_days, 0)
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
          u.created_at as signup_at,
          coalesce(cost.total_micros, 0) as api_cost_usd_micros,
          (completed.user_id is not null) as tutorial_completed,
          last_event.occurred_at as last_event_at
        from auth.users u
        left join (
          select user_id, sum(cost_usd_micros)::bigint as total_micros
          from public.ai_usage_events
          where status = 'finalized'
          group by user_id
        ) cost on cost.user_id = u.id
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
  signup_at timestamptz;
begin
  perform public._admin_require();
  if p_user_id is null then
    raise exception 'invalid_user';
  end if;

  select u.email::text, u.created_at
  into email, signup_at
  from auth.users u
  where u.id = p_user_id;
  if not found then
    raise exception 'user_not_found';
  end if;

  return jsonb_build_object(
    'user_id', p_user_id,
    'email', email,
    'signup_at', signup_at,
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
            sum(e.cost_usd_micros)::bigint as api_cost_usd_micros
          from public.ai_usage_events e
          join auth.users u on u.id = e.user_id
          where e.status = 'finalized'
          group by e.user_id, u.email
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
