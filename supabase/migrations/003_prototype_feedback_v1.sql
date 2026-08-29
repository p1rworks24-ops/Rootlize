-- Prototype Guided Experience feedback and funnel events.
-- No image, path, filename, query, facts, or OCR columns.
-- Apply this file in the Supabase SQL editor. Table Editor can open
-- public.prototype_feedback to inspect one row per submitted answer.

create table if not exists public.prototype_feedback (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references auth.users (id) on delete set null,
  prototype_session_id text not null,
  completed_at timestamptz not null default now(),
  app_version text,
  feedback_version text,
  most_useful text,
  would_use text,
  easier_than_current text,
  confusing_text text,
  willingness_to_pay text
);

create table if not exists public.prototype_analytics (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references auth.users (id) on delete set null,
  prototype_session_id text not null,
  event_name text not null,
  occurred_at timestamptz not null default now()
);

-- Existing deployments that already applied an older 003 keep old columns
-- and gain the current field names used by the desktop client.
alter table public.prototype_feedback add column if not exists app_version text;
alter table public.prototype_feedback add column if not exists feedback_version text;
alter table public.prototype_feedback add column if not exists most_useful text;
alter table public.prototype_feedback add column if not exists would_use text;
alter table public.prototype_feedback add column if not exists easier_than_current text;
alter table public.prototype_feedback add column if not exists confusing_text text;
alter table public.prototype_feedback add column if not exists willingness_to_pay text;

create index if not exists prototype_feedback_session_idx
  on public.prototype_feedback (prototype_session_id);
create index if not exists prototype_analytics_session_idx
  on public.prototype_analytics (prototype_session_id, occurred_at);

alter table public.prototype_feedback enable row level security;
alter table public.prototype_analytics enable row level security;

drop policy if exists prototype_feedback_insert_auth on public.prototype_feedback;
create policy prototype_feedback_insert_auth on public.prototype_feedback
  for insert to authenticated
  with check (user_id is null or user_id = auth.uid());

drop policy if exists prototype_feedback_insert_anon on public.prototype_feedback;
create policy prototype_feedback_insert_anon on public.prototype_feedback
  for insert to anon
  with check (user_id is null);

drop policy if exists prototype_feedback_select_own on public.prototype_feedback;
create policy prototype_feedback_select_own on public.prototype_feedback
  for select to authenticated
  using (user_id = auth.uid());

drop policy if exists prototype_analytics_insert_auth on public.prototype_analytics;
create policy prototype_analytics_insert_auth on public.prototype_analytics
  for insert to authenticated
  with check (user_id is null or user_id = auth.uid());

drop policy if exists prototype_analytics_insert_anon on public.prototype_analytics;
create policy prototype_analytics_insert_anon on public.prototype_analytics
  for insert to anon
  with check (user_id is null);

drop policy if exists prototype_analytics_select_own on public.prototype_analytics;
create policy prototype_analytics_select_own on public.prototype_analytics
  for select to authenticated
  using (user_id = auth.uid());
