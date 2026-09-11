-- Fraktall remote-control MVP
-- Run this once in a dedicated Supabase project's SQL editor.

create extension if not exists pgcrypto;

create table if not exists public.fraktall_jobs (
  id uuid primary key default gen_random_uuid(),
  source_url text not null,
  curation_mode text not null default 'podcast',
  clip_count integer not null default 8 check (clip_count between 1 and 40),
  status text not null default 'queued' check (status in ('queued','claimed','running','done','error','cancelled')),
  stage text,
  progress integer not null default 0 check (progress between 0 and 100),
  worker_id text,
  result jsonb,
  error text,
  created_at timestamptz not null default now(),
  claimed_at timestamptz,
  started_at timestamptz,
  finished_at timestamptz,
  updated_at timestamptz not null default now()
);

create index if not exists fraktall_jobs_queue_idx
  on public.fraktall_jobs (status, created_at);

create table if not exists public.fraktall_workers (
  id text primary key,
  status text not null default 'idle',
  current_job uuid references public.fraktall_jobs(id) on delete set null,
  last_seen timestamptz not null default now(),
  metadata jsonb not null default '{}'::jsonb
);

-- Only server-side components use the service-role key in this MVP.
-- No browser is allowed to access these tables directly.
alter table public.fraktall_jobs enable row level security;
alter table public.fraktall_workers enable row level security;

revoke all on public.fraktall_jobs from anon, authenticated;
revoke all on public.fraktall_workers from anon, authenticated;
