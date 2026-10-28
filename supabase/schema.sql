create extension if not exists pgcrypto;
create table if not exists public.participants (
 telegram_id bigint primary key,
 username text,
 display_name text not null default 'LEGEND member',
 referral_code text not null unique,
 referred_by bigint references public.participants(telegram_id) on delete set null,
 human_verified boolean not null default false,
 human_verified_at timestamptz,
 challenge_answer text,
 challenge_expires_at timestamptz,
 membership_status text not null default 'unknown' check (membership_status in ('unknown','member','left')),
 joined_at timestamptz,
 qualified_at timestamptz,
 created_at timestamptz not null default now(),
 constraint no_self_referral check (referred_by is null or referred_by <> telegram_id)
);
create table if not exists public.referrals (
 id uuid primary key default gen_random_uuid(),
 invitee_telegram_id bigint not null unique references public.participants(telegram_id) on delete cascade,
 referrer_telegram_id bigint not null references public.participants(telegram_id) on delete cascade,
 status text not null default 'pending' check (status in ('pending','eligible','revoked','under_review')),
 qualified_at timestamptz,
 created_at timestamptz not null default now(),
 constraint referral_not_self check (invitee_telegram_id <> referrer_telegram_id)
);
create index if not exists referrals_referrer_status_idx on public.referrals(referrer_telegram_id,status);
create index if not exists participants_qualification_idx on public.participants(membership_status,qualified_at);
alter table public.participants enable row level security;
alter table public.referrals enable row level security;
revoke all on public.participants from anon, authenticated;
revoke all on public.referrals from anon, authenticated;
grant all on public.participants to service_role;
grant all on public.referrals to service_role;
