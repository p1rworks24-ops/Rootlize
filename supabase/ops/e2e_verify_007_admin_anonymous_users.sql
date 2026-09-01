-- Read-only. Confirms 007_admin_anonymous_users_v1.sql is on this project.
-- Safe to run on live. Does not write.
-- Does not change entitlements, usage ledgers, or plan_defaults amounts.

select
  to_regprocedure('public.admin_get_overview()') as admin_get_overview,
  to_regprocedure('public.admin_get_users()') as admin_get_users,
  to_regprocedure('public.admin_get_user_activity(uuid)') as admin_get_user_activity,
  to_regprocedure('public.admin_get_api_usage()') as admin_get_api_usage;

select
  pg_get_functiondef(to_regprocedure('public.admin_get_users()'))
    like '%u.is_anonymous%' as users_use_auth_is_anonymous,
  pg_get_functiondef(to_regprocedure('public.admin_get_users()'))
    like '%raw_user_meta_data%' as users_use_client_metadata,
  pg_get_functiondef(to_regprocedure('public.admin_get_users()'))
    like '%ai_lifetime_hard_cap_micros%' as users_use_hard_cap,
  pg_get_functiondef(to_regprocedure('public.admin_get_users()'))
    like '%ai_usage_lifetime%' as users_use_lifetime_usage,
  pg_get_functiondef(to_regprocedure('public.admin_get_users()'))
    like '%public.devices%' as users_include_devices,
  pg_get_functiondef(to_regprocedure('public.admin_get_overview()'))
    like '%anonymous%' as overview_splits_anonymous,
  pg_get_functiondef(to_regprocedure('public.admin_get_overview()'))
    like '%prototype%' as overview_counts_prototype,
  pg_get_functiondef(to_regprocedure('public.admin_get_user_activity(uuid)'))
    like '%is_anonymous%' as activity_includes_anonymous,
  pg_get_functiondef(to_regprocedure('public.admin_get_api_usage()'))
    like '%is_anonymous%' as api_usage_includes_anonymous;

select
  has_function_privilege('anon', 'public.admin_get_overview()', 'EXECUTE') as anon_can_overview,
  has_function_privilege('authenticated', 'public.admin_get_overview()', 'EXECUTE') as auth_can_overview,
  has_function_privilege('anon', 'public.admin_get_users()', 'EXECUTE') as anon_can_users,
  has_function_privilege('authenticated', 'public.admin_get_users()', 'EXECUTE') as auth_can_users;
