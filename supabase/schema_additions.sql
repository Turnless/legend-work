-- Run this once in the same Supabase project used by the bot/API.
alter table public.participants
  add column if not exists challenge_answer text,
  add column if not exists challenge_expires_at timestamptz;
