begin;

alter table public.accounts
  add column if not exists auth_user_id uuid;

alter table public.accounts
  alter column password drop not null;

do $$
begin
  if not exists (
    select 1 from pg_constraint where conname = 'accounts_auth_user_id_fkey'
  ) then
    alter table public.accounts
      add constraint accounts_auth_user_id_fkey
      foreign key (auth_user_id) references auth.users(id) on delete cascade;
  end if;
end $$;

create unique index if not exists accounts_auth_user_id_key
  on public.accounts (auth_user_id)
  where auth_user_id is not null;

alter table public.jobs
  add column if not exists owner_user_id uuid references auth.users(id) on delete set null;

alter table public.applications
  add column if not exists worker_user_id uuid references auth.users(id) on delete set null,
  add column if not exists company_user_id uuid references auth.users(id) on delete set null;

alter table public.attendance
  add column if not exists worker_user_id uuid references auth.users(id) on delete set null,
  add column if not exists company_user_id uuid references auth.users(id) on delete set null;

alter table public.worker_push_tokens
  add column if not exists owner_user_id uuid references auth.users(id) on delete cascade;

alter table public.push_notification_logs
  add column if not exists caller_user_id uuid references auth.users(id) on delete set null;

create index if not exists jobs_owner_user_id_idx on public.jobs(owner_user_id);
create index if not exists applications_job_id_idx on public.applications(job_id);
create index if not exists applications_worker_user_id_idx on public.applications(worker_user_id);
create index if not exists applications_company_user_id_idx on public.applications(company_user_id);
create index if not exists attendance_job_id_idx on public.attendance(job_id);
create index if not exists attendance_worker_user_id_idx on public.attendance(worker_user_id);
create index if not exists attendance_company_user_id_idx on public.attendance(company_user_id);
create index if not exists worker_push_tokens_owner_user_id_idx on public.worker_push_tokens(owner_user_id);

create table if not exists public.wexa_auth_rate_limits (
  id bigint generated always as identity primary key,
  scope text not null,
  actor_hash text not null,
  created_at timestamptz not null default now()
);

alter table public.wexa_auth_rate_limits enable row level security;
revoke all on public.wexa_auth_rate_limits from anon, authenticated;
grant all on public.wexa_auth_rate_limits to service_role;
create index if not exists wexa_auth_rate_limits_lookup_idx
  on public.wexa_auth_rate_limits(scope, actor_hash, created_at desc);

create table if not exists public.wexa_system_settings (
  key text primary key,
  value jsonb not null default '{}'::jsonb,
  used_at timestamptz,
  updated_at timestamptz not null default now()
);

alter table public.wexa_system_settings enable row level security;
revoke all on public.wexa_system_settings from anon, authenticated;
grant all on public.wexa_system_settings to service_role;

commit;
