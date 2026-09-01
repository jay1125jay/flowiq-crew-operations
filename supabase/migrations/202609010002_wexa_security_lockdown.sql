begin;

create or replace function public.wexa_current_role()
returns text
language sql
stable
security invoker
set search_path = ''
as $$
  select coalesce((select auth.jwt()) -> 'app_metadata' ->> 'role', '');
$$;

create or replace function public.wexa_guard_job_write()
returns trigger
language plpgsql
security invoker
set search_path = public, pg_temp
as $$
declare
  actor uuid := auth.uid();
  actor_role text := public.wexa_current_role();
  normalized_type text;
begin
  if actor is null then
    raise exception 'AUTH_REQUIRED';
  end if;

  if actor_role = 'admin' then
    return new;
  end if;

  if actor_role not in ('business', 'personal') then
    raise exception 'BUSINESS_ROLE_REQUIRED';
  end if;

  if new.owner_user_id is distinct from actor then
    raise exception 'JOB_OWNER_MISMATCH';
  end if;

  normalized_type := regexp_replace(coalesce(new.type, ''), '\s+', '', 'g');

  if tg_op = 'INSERT' and normalized_type not like '%게시대기%' then
    raise exception 'JOB_MUST_START_PENDING';
  end if;

  if tg_op = 'UPDATE' then
    if old.owner_user_id is distinct from actor
      or new.owner_user_id is distinct from old.owner_user_id
      or new.company_id is distinct from old.company_id then
      raise exception 'JOB_IDENTITY_IMMUTABLE';
    end if;

    if regexp_replace(coalesce(old.type, ''), '\s+', '', 'g') not like '%게시중%'
      and normalized_type like '%게시중%' then
      raise exception 'MASTER_APPROVAL_REQUIRED';
    end if;

    if normalized_type like '%보관%' then
      raise exception 'MASTER_ARCHIVE_REQUIRED';
    end if;
  end if;

  return new;
end;
$$;

create or replace function public.wexa_guard_application_write()
returns trigger
language plpgsql
security invoker
set search_path = public, pg_temp
as $$
declare
  actor uuid := auth.uid();
  actor_role text := public.wexa_current_role();
  old_status text;
  new_status text;
begin
  if actor is null then
    raise exception 'AUTH_REQUIRED';
  end if;

  if actor_role = 'admin' then
    return new;
  end if;

  new_status := regexp_replace(coalesce(new.status, ''), '\s+', '', 'g');

  if tg_op = 'INSERT' then
    if actor_role <> 'worker'
      or new.worker_user_id is distinct from actor
      or new_status <> '지원' then
      raise exception 'INVALID_APPLICATION_CREATE';
    end if;
    return new;
  end if;

  old_status := regexp_replace(coalesce(old.status, ''), '\s+', '', 'g');

  if new.job_id is distinct from old.job_id
    or new.worker_user_id is distinct from old.worker_user_id
    or new.company_user_id is distinct from old.company_user_id
    or new.phone is distinct from old.phone then
    raise exception 'APPLICATION_IDENTITY_IMMUTABLE';
  end if;

  if actor_role = 'worker' then
    if old.worker_user_id is distinct from actor
      or not (old_status = '지원' and new_status = '신청취소') then
      raise exception 'WORKER_STATUS_TRANSITION_DENIED';
    end if;
    return new;
  end if;

  if actor_role in ('business', 'personal') then
    if old.company_user_id is distinct from actor then
      raise exception 'COMPANY_APPLICATION_MISMATCH';
    end if;

    if not (
      (old_status = '지원' and new_status in ('승인', '신청반려', '미선정'))
      or (old_status = '승인' and new_status in ('근무완료', '매칭취소'))
    ) then
      raise exception 'COMPANY_STATUS_TRANSITION_DENIED';
    end if;
    return new;
  end if;

  raise exception 'ROLE_DENIED';
end;
$$;

drop trigger if exists wexa_jobs_write_guard on public.jobs;
create trigger wexa_jobs_write_guard
before insert or update on public.jobs
for each row execute function public.wexa_guard_job_write();

drop trigger if exists wexa_applications_write_guard on public.applications;
create trigger wexa_applications_write_guard
before insert or update on public.applications
for each row execute function public.wexa_guard_application_write();

alter table public.accounts enable row level security;
alter table public.jobs enable row level security;
alter table public.applications enable row level security;
alter table public.attendance enable row level security;
alter table public.worker_push_tokens enable row level security;
alter table public.push_notification_logs enable row level security;
alter table public.users enable row level security;
alter table public.matches enable row level security;

do $$
declare
  policy_row record;
begin
  for policy_row in
    select schemaname, tablename, policyname
    from pg_policies
    where schemaname = 'public'
      and tablename in (
        'accounts', 'jobs', 'applications', 'attendance',
        'worker_push_tokens', 'push_notification_logs', 'users', 'matches'
      )
  loop
    execute format(
      'drop policy if exists %I on %I.%I',
      policy_row.policyname,
      policy_row.schemaname,
      policy_row.tablename
    );
  end loop;
end $$;

create policy accounts_select_own_or_admin
on public.accounts for select
to authenticated
using (
  auth_user_id = (select auth.uid())
  or public.wexa_current_role() = 'admin'
);

create policy accounts_update_own_or_admin
on public.accounts for update
to authenticated
using (
  auth_user_id = (select auth.uid())
  or public.wexa_current_role() = 'admin'
)
with check (
  auth_user_id = (select auth.uid())
  or public.wexa_current_role() = 'admin'
);

create policy jobs_select_authorized
on public.jobs for select
to authenticated
using (
  public.wexa_current_role() = 'admin'
  or owner_user_id = (select auth.uid())
  or (
    public.wexa_current_role() = 'worker'
    and (
      (
        regexp_replace(coalesce(type, ''), '\s+', '', 'g') like '%게시중%'
        and regexp_replace(coalesce(type, ''), '\s+', '', 'g') not like '%공고마감%'
        and regexp_replace(coalesce(type, ''), '\s+', '', 'g') not like '%보관%'
      )
      or exists (
        select 1
        from public.applications a
        where a.job_id = jobs.id
          and a.worker_user_id = (select auth.uid())
      )
    )
  )
);

create policy jobs_insert_business
on public.jobs for insert
to authenticated
with check (
  public.wexa_current_role() in ('business', 'personal')
  and owner_user_id = (select auth.uid())
  and regexp_replace(coalesce(type, ''), '\s+', '', 'g') like '%게시대기%'
);

create policy jobs_update_owner_or_admin
on public.jobs for update
to authenticated
using (
  public.wexa_current_role() = 'admin'
  or owner_user_id = (select auth.uid())
)
with check (
  public.wexa_current_role() = 'admin'
  or owner_user_id = (select auth.uid())
);

create policy jobs_delete_admin
on public.jobs for delete
to authenticated
using (public.wexa_current_role() = 'admin');

create policy applications_select_authorized
on public.applications for select
to authenticated
using (
  public.wexa_current_role() = 'admin'
  or worker_user_id = (select auth.uid())
  or company_user_id = (select auth.uid())
);

create policy applications_insert_worker
on public.applications for insert
to authenticated
with check (
  public.wexa_current_role() = 'worker'
  and worker_user_id = (select auth.uid())
  and regexp_replace(coalesce(status, ''), '\s+', '', 'g') = '지원'
  and company_user_id is not distinct from (
    select j.owner_user_id from public.jobs j where j.id = job_id
  )
);

create policy applications_update_owner
on public.applications for update
to authenticated
using (
  public.wexa_current_role() = 'admin'
  or worker_user_id = (select auth.uid())
  or company_user_id = (select auth.uid())
)
with check (
  public.wexa_current_role() = 'admin'
  or worker_user_id = (select auth.uid())
  or company_user_id = (select auth.uid())
);

create policy applications_delete_admin
on public.applications for delete
to authenticated
using (public.wexa_current_role() = 'admin');

create policy attendance_select_authorized
on public.attendance for select
to authenticated
using (
  public.wexa_current_role() = 'admin'
  or worker_user_id = (select auth.uid())
  or company_user_id = (select auth.uid())
);

create policy attendance_insert_worker
on public.attendance for insert
to authenticated
with check (
  public.wexa_current_role() = 'worker'
  and worker_user_id = (select auth.uid())
);

create policy worker_push_tokens_select_own_or_admin
on public.worker_push_tokens for select
to authenticated
using (
  owner_user_id = (select auth.uid())
  or public.wexa_current_role() = 'admin'
);

create policy worker_push_tokens_insert_own
on public.worker_push_tokens for insert
to authenticated
with check (owner_user_id = (select auth.uid()));

create policy worker_push_tokens_update_own_or_admin
on public.worker_push_tokens for update
to authenticated
using (
  owner_user_id = (select auth.uid())
  or public.wexa_current_role() = 'admin'
)
with check (
  owner_user_id = (select auth.uid())
  or public.wexa_current_role() = 'admin'
);

create policy worker_push_tokens_delete_own_or_admin
on public.worker_push_tokens for delete
to authenticated
using (
  owner_user_id = (select auth.uid())
  or public.wexa_current_role() = 'admin'
);

create policy push_logs_select_admin
on public.push_notification_logs for select
to authenticated
using (public.wexa_current_role() = 'admin');

revoke all on all tables in schema public from anon;
revoke all on all sequences in schema public from anon;
revoke all on all tables in schema public from authenticated;

grant usage on schema public to anon, authenticated;
grant select on public.accounts to authenticated;
grant update (name, business_no, resident, bank, account, holder) on public.accounts to authenticated;
grant select, insert, update, delete on public.jobs to authenticated;
grant select, insert, update, delete on public.applications to authenticated;
grant select, insert on public.attendance to authenticated;
grant select, insert, update, delete on public.worker_push_tokens to authenticated;
grant select on public.push_notification_logs to authenticated;
grant usage, select on all sequences in schema public to authenticated;

grant execute on function public.wexa_current_role() to authenticated;
revoke execute on function public.wexa_guard_job_write() from public, anon, authenticated;
revoke execute on function public.wexa_guard_application_write() from public, anon, authenticated;

commit;
