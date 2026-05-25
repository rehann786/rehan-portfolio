'use client';
/**
 * app/admin/page.tsx
 * --------------------------------------------------------------
 * Simple analytics dashboard.
 *
 * Shows aggregate counts and a recent-events table read from the
 * Supabase `portfolio_clicks` table.
 *
 * SECURITY NOTE — please read:
 * This page uses a basic password gate. The password is compared on
 * the CLIENT against NEXT_PUBLIC... NO — to keep the password off the
 * client we compare it via the /api/track-click pattern would be
 * overkill, so instead this gate is intentionally simple:
 *   - It is "obscurity" protection, fine for a personal portfolio.
 *   - It is NOT real security. Anyone determined can read your data
 *     if your Supabase table allows public SELECT.
 * For production, use Supabase Auth + Row Level Security so only an
 * authenticated admin can SELECT rows. See the README.
 */
import { useState, useEffect } from 'react';
import { getSupabase, ClickEvent } from '@/lib/supabase';

export default function AdminPage() {
  const [authed, setAuthed] = useState(false);
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [events, setEvents] = useState<ClickEvent[]>([]);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState('');

  // The expected password. Set ADMIN_PASSWORD in your env.
  // We expose it here as NEXT_PUBLIC for the simple client gate;
  // see the security note above for the production-grade approach.
  const expected =
    process.env.NEXT_PUBLIC_ADMIN_PASSWORD || process.env.ADMIN_PASSWORD;

  function checkPassword() {
    if (!expected) {
      // If no password configured, allow in but warn.
      setAuthed(true);
      return;
    }
    if (password === expected) {
      setAuthed(true);
      setError('');
    } else {
      setError('Incorrect password.');
    }
  }

  // Load events once authenticated.
  useEffect(() => {
    if (!authed) return;

    async function load() {
      setLoading(true);
      setLoadError('');
      const supabase = getSupabase();
      if (!supabase) {
        setLoadError('Supabase is not configured yet.');
        setLoading(false);
        return;
      }
      const { data, error } = await supabase
        .from('portfolio_clicks')
        .select('*')
        .order('created_at', { ascending: false })
        .limit(500);

      if (error) {
        setLoadError(error.message);
      } else {
        setEvents((data as ClickEvent[]) || []);
      }
      setLoading(false);
    }
    load();
  }, [authed]);

  // ---- Aggregate metrics --------------------------------------
  const count = (name: string) =>
    events.filter((e) => e.event_name === name).length;

  const metrics = [
    { label: 'Total Clicks', value: events.length },
    { label: 'Resume Downloads', value: count('resume_download_click') },
    { label: 'GitHub Clicks', value: count('github_click') },
    { label: 'LinkedIn Clicks', value: count('linkedin_click') },
    { label: 'Contact Submissions', value: count('contact_form_submit') },
    {
      label: 'Project Clicks',
      value:
        count('project_demo_click') + count('project_github_click'),
    },
  ];

  // ---- Password gate UI ---------------------------------------
  if (!authed) {
    return (
      <main className="min-h-screen grid place-items-center bg-grid px-6">
        <div className="w-full max-w-sm bg-coal border border-steel/60 rounded-xl p-7">
          <h1 className="font-display font-bold text-xl">Admin Access</h1>
          <p className="text-sm text-ash mt-1">
            Enter the dashboard password.
          </p>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && checkPassword()}
            className="mt-5 w-full px-3 py-2.5 rounded-lg bg-slate border border-steel text-chalk text-sm focus:outline-none focus:border-gold"
            placeholder="Password"
          />
          {error && (
            <p className="text-sm text-red-400 mt-2">{error}</p>
          )}
          <button
            onClick={checkPassword}
            className="mt-4 w-full px-4 py-2.5 rounded-lg bg-gold text-ink font-semibold hover:bg-goldDark transition-colors"
          >
            Enter
          </button>
          <p className="text-[11px] text-ash mt-4 leading-relaxed">
            This is simple password protection only. For real security, use
            Supabase Auth — see the project README.
          </p>
        </div>
      </main>
    );
  }

  // ---- Dashboard UI -------------------------------------------
  return (
    <main className="min-h-screen bg-ink px-6 py-12">
      <div className="max-w-6xl mx-auto">
        <div className="flex items-baseline justify-between flex-wrap gap-2">
          <h1 className="font-display font-bold text-3xl">
            Analytics Dashboard
          </h1>
          <a href="/" className="text-sm text-gold hover:underline">
            ← Back to site
          </a>
        </div>
        <p className="text-ash text-sm mt-1">
          Custom click events logged from your portfolio.
        </p>

        {loadError && (
          <div className="mt-6 bg-coal border border-red-500/40 rounded-lg p-4 text-sm text-red-300">
            {loadError}
          </div>
        )}

        {/* Metric cards */}
        <div className="mt-8 grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-4">
          {metrics.map((m) => (
            <div
              key={m.label}
              className="bg-coal border border-steel/60 rounded-xl p-5"
            >
              <div className="font-display text-3xl font-bold text-gold">
                {loading ? '—' : m.value}
              </div>
              <div className="text-xs text-ash mt-1">{m.label}</div>
            </div>
          ))}
        </div>

        {/* Recent events table */}
        <div className="mt-10">
          <h2 className="font-display font-semibold text-lg mb-4">
            Recent Click Events
          </h2>
          <div className="bg-coal border border-steel/60 rounded-xl overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-ash border-b border-steel/60">
                  <th className="px-4 py-3 font-medium">Event</th>
                  <th className="px-4 py-3 font-medium">Category</th>
                  <th className="px-4 py-3 font-medium">Label</th>
                  <th className="px-4 py-3 font-medium">Page</th>
                  <th className="px-4 py-3 font-medium">Source</th>
                  <th className="px-4 py-3 font-medium">Time</th>
                </tr>
              </thead>
              <tbody>
                {loading && (
                  <tr>
                    <td colSpan={6} className="px-4 py-8 text-center text-ash">
                      Loading…
                    </td>
                  </tr>
                )}
                {!loading && events.length === 0 && (
                  <tr>
                    <td colSpan={6} className="px-4 py-8 text-center text-ash">
                      No events yet. Click around your site to generate some.
                    </td>
                  </tr>
                )}
                {events.map((e, i) => (
                  <tr
                    key={e.id || i}
                    className="border-b border-steel/30 hover:bg-slate/40"
                  >
                    <td className="px-4 py-3 font-mono text-gold text-xs">
                      {e.event_name}
                    </td>
                    <td className="px-4 py-3 text-ash">{e.event_category}</td>
                    <td className="px-4 py-3 text-chalk">{e.event_label}</td>
                    <td className="px-4 py-3 text-ash">{e.page_path}</td>
                    <td className="px-4 py-3">
                      <span className="px-2 py-0.5 rounded bg-slate text-xs text-ash border border-steel/60">
                        {e.source}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-ash text-xs">
                      {e.created_at
                        ? new Date(e.created_at).toLocaleString()
                        : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </main>
  );
}
