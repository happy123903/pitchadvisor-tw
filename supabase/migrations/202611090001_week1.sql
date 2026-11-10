-- Week-one versioned read model. Apply to a new Supabase project only.
begin;

create table if not exists public.model_versions (
  model_version text primary key,
  data_version text not null,
  data_cutoff date not null,
  model_name text not null,
  storage_path text not null,
  sha256 text not null check (length(sha256) = 64),
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create table if not exists public.players (
  id text not null,
  role text not null check (role in ('pitcher','batter')),
  data_version text not null,
  name text not null,
  hand text,
  sample_count integer not null check (sample_count >= 0),
  primary key (id,role,data_version)
);
create index if not exists players_role_version_idx on public.players(data_version,role);

create table if not exists public.pitcher_repertoire (
  pitcher_id text not null,
  data_version text not null,
  pitch_type text not null,
  sample_count integer not null check (sample_count > 0),
  primary key (pitcher_id,data_version,pitch_type)
);

create table if not exists public.aggregate_stats (
  data_version text not null,
  scope text not null,
  lookup_key text not null,
  stats jsonb not null,
  primary key (data_version,scope,lookup_key)
);

alter table public.model_versions enable row level security;
alter table public.players enable row level security;
alter table public.pitcher_repertoire enable row level security;
alter table public.aggregate_stats enable row level security;

-- No anonymous/authenticated policies: clients access the limited FastAPI API.
revoke all on public.model_versions,public.players,public.pitcher_repertoire,public.aggregate_stats from anon,authenticated;
grant select,insert,update on public.model_versions,public.players,public.pitcher_repertoire,public.aggregate_stats to service_role;

insert into storage.buckets(id,name,public,file_size_limit,allowed_mime_types)
values ('model-artifacts','model-artifacts',false,20971520,array['application/json'])
on conflict(id) do update set public=false;
-- No public Storage policies are created; service credentials stay server-side.

commit;
