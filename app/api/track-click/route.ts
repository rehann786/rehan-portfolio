/**
 * app/api/track-click/route.ts
 * --------------------------------------------------------------
 * POST endpoint that records a click/interaction event into the
 * Supabase `portfolio_clicks` table.
 *
 * It only stores non-sensitive analytics fields. It never stores a
 * visitor's name, IP, or any personal identity data.
 */
import { NextRequest, NextResponse } from 'next/server';
import { getSupabase, ClickEvent } from '@/lib/supabase';

export async function POST(req: NextRequest) {
  try {
    const body = (await req.json()) as Partial<ClickEvent>;

    // Basic validation — require an event name.
    if (!body.event_name) {
      return NextResponse.json(
        { ok: false, error: 'event_name is required' },
        { status: 400 }
      );
    }

    const supabase = getSupabase();

    // If Supabase isn't configured, don't error — just acknowledge.
    // This keeps the site working before Supabase setup is complete.
    if (!supabase) {
      return NextResponse.json({
        ok: true,
        stored: false,
        note: 'Supabase not configured — event not persisted.',
      });
    }

    // Only these fields are persisted. Nothing personal.
    const row: ClickEvent = {
      event_name: String(body.event_name).slice(0, 120),
      event_category: String(body.event_category || 'general').slice(0, 80),
      event_label: String(body.event_label || '').slice(0, 200),
      page_path: String(body.page_path || '/').slice(0, 200),
      source: String(body.source || 'direct').slice(0, 80),
    };

    const { error } = await supabase.from('portfolio_clicks').insert(row);

    if (error) {
      return NextResponse.json(
        { ok: false, error: error.message },
        { status: 500 }
      );
    }

    return NextResponse.json({ ok: true, stored: true });
  } catch (err) {
    return NextResponse.json(
      { ok: false, error: 'Invalid request' },
      { status: 400 }
    );
  }
}
