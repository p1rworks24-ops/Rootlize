-- Read-only. Confirms 005_admin_analytics_v1.sql is on this project.
-- Apply 005 after 001, 002, 003, and 004.

select
  to_regclass('public.admin_users') as admin_users,
  to_regclass('public.website_analytics') as website_analytics;

select
  to_regprocedure('public.is_rootlize_admin()') as is_rootlize_admin,
  to_regprocedure('public._admin_require()') as admin_require,
  to_regprocedure('public.admin_get_overview()') as admin_get_overview,
  to_regprocedure('public.admin_get_users()') as admin_get_users,
  to_regprocedure('public.admin_get_user_activity(uuid)') as admin_get_user_activity,
  to_regprocedure('public.admin_get_api_usage()') as admin_get_api_usage;

select
  has_table_privilege('anon', 'public.website_analytics', 'INSERT') as anon_can_insert_website,
  has_table_privilege('anon', 'public.website_analytics', 'SELECT') as anon_can_select_website,
  has_table_privilege('authenticated', 'public.website_analytics', 'SELECT') as auth_can_select_website,
  has_table_privilege('authenticated', 'public.admin_users', 'SELECT') as auth_can_select_admins;

select
  has_function_privilege('anon', 'public.admin_get_overview()', 'EXECUTE') as anon_can_overview,
  has_function_privilege('authenticated', 'public.admin_get_overview()', 'EXECUTE') as auth_can_overview,
  has_function_privilege('anon', 'public.admin_get_users()', 'EXECUTE') as anon_can_users,
  has_function_privilege('authenticated', 'public.admin_get_users()', 'EXECUTE') as auth_can_users;
