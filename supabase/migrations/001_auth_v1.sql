-- Capixe Auth v1. Apply in the Supabase SQL editor.
-- Desktop clients use the publishable (anon) key only.
-- RLS: users may read their own rows. Plan/status writes are service_role only.

create table if not exists public.profiles (
  user_id uuid primary key references auth.users (id) on delete cascade,
  display_name text not null default '',
  created_at timestamptz not null default now()
);

create table if not exists public.devices (
  device_id uuid primary key,
  user_id uuid not null references auth.users (id) on delete cascade,
  device_name text not null default '',
  platform text not null default '',
  last_seen_at timestamptz not null default now()
);

create index if not exists devices_user_id_idx on public.devices (user_id);

create table if not exists public.entitlements (
  user_id uuid primary key references auth.users (id) on delete cascade,
  plan text not null default 'free',
  account_status text not null default 'active',
  ai_allowed boolean not null default true,
  updated_at timestamptz not null default now()
);

alter table public.profiles enable row level security;
alter table public.devices enable row level security;
alter table public.entitlements enable row level security;

drop policy if exists profiles_select_own on public.profiles;
create policy profiles_select_own on public.profiles
  for select to authenticated
  using (auth.uid() = user_id);

drop policy if exists profiles_insert_own on public.profiles;
create policy profiles_insert_own on public.profiles
  for insert to authenticated
  with check (auth.uid() = user_id);

drop policy if exists profiles_update_own on public.profiles;
create policy profiles_update_own on public.profiles
  for update to authenticated
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);

drop policy if exists devices_select_own on public.devices;
create policy devices_select_own on public.devices
  for select to authenticated
  using (auth.uid() = user_id);

drop policy if exists devices_insert_own on public.devices;
create policy devices_insert_own on public.devices
  for insert to authenticated
  with check (auth.uid() = user_id);

drop policy if exists devices_update_own on public.devices;
create policy devices_update_own on public.devices
  for update to authenticated
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);

drop policy if exists entitlements_select_own on public.entitlements;
create policy entitlements_select_own on public.entitlements
  for select to authenticated
  using (auth.uid() = user_id);

-- No insert/update/delete policies for entitlements for `authenticated`.
-- plan / account_status / ai_allowed are server/admin (service_role) only.

create or replace function public.handle_new_capixe_user()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  insert into public.profiles (user_id, display_name)
  values (new.id, coalesce(new.raw_user_meta_data->>'full_name', split_part(new.email, '@', 1), ''))
  on conflict (user_id) do nothing;
  insert into public.entitlements (user_id, plan, account_status, ai_allowed)
  values (new.id, 'free', 'active', true)
  on conflict (user_id) do nothing;
  return new;
end;
$$;

drop trigger if exists on_auth_user_created_capixe on auth.users;
create trigger on_auth_user_created_capixe
  after insert on auth.users
  for each row execute function public.handle_new_capixe_user();

revoke all on public.entitlements from anon;
grant select on public.profiles, public.devices, public.entitlements to authenticated;
grant insert, update on public.profiles, public.devices to authenticated;
