/**
 * lib/supabase.ts
 * --------------------------------------------------------------
 * Supabase client used for custom click tracking.
 * Uses the public anon key (safe for the browser since the
 * portfolio_clicks table only allows INSERT from anon, and SELECT
 * is done server-side / behind the admin password gate).
 */
import { createClient, SupabaseClient } from '@supabase/supabase-js';

const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
const anonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

/**
 * Returns a Supabase client, or null if env vars are missing.
 * Callers must handle the null case so the site still works
 * before Supabase is configured.
 */
export function getSupabase(): SupabaseClient | null {
  if (!url || !anonKey) {
    return null;
  }
  return createClient(url, anonKey);
}

// Shape of a row in the portfolio_clicks table.
export type ClickEvent = {
  id?: string;
  event_name: string;
  event_category: string;
  event_label: string;
  page_path: string;
  source: string;
  created_at?: string;
};
