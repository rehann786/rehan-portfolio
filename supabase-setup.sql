-- ============================================================
--  Supabase setup for the portfolio click-tracking feature.
--  Run this in:  Supabase Dashboard -> SQL Editor -> New query
-- ============================================================

-- 1) The click events table -----------------------------------
create table if not exists portfolio_clicks (
  id             uuid primary key default gen_random_uuid(),
  event_name     text not null,
  event_category text,
  event_label    text,
  page_path      text,
  source         text,
  created_at     timestamptz not null default now()
);

-- Helpful index for the admin dashboard (newest first).
create index if not exists portfolio_clicks_created_at_idx
  on portfolio_clicks (created_at desc);


-- 2) Row Level Security ---------------------------------------
-- We enable RLS, then add policies that allow:
--   * anyone (anon) to INSERT a click event
--   * anyone (anon) to SELECT click events  (so the simple
--     password-gated /admin page can read them)
--
-- NOTE: Allowing public SELECT means your click data is technically
-- readable by anyone who has your anon key. For a personal portfolio
-- this is usually acceptable (no personal data is stored). For real
-- security, REMOVE the SELECT policy below and use Supabase Auth so
-- only your logged-in admin account can read the table.

alter table portfolio_clicks enable row level security;

-- Allow inserts from the website (anon role).
create policy "allow anon inserts"
  on portfolio_clicks
  for insert
  to anon
  with check (true);

-- Allow reads (used by the /admin dashboard).
-- COMMENT THIS OUT for production + use Supabase Auth instead.
create policy "allow anon reads"
  on portfolio_clicks
  for select
  to anon
  using (true);
