/**
 * lib/analytics.ts
 * --------------------------------------------------------------
 * Central analytics utilities.
 *
 * trackEvent() does TWO things for every event:
 *   1. Sends the event to Google Analytics 4 (via gtag).
 *   2. Sends the event to our own /api/track-click route,
 *      which logs it into the Supabase `portfolio_clicks` table.
 *
 * It also reads a "source" value (e.g. ?source=linkedin) that was
 * stored in localStorage on first visit, so every click is attributed
 * to where the visitor came from.
 *
 * PRIVACY: We never collect a visitor's name automatically. The only
 * way to know who someone is, is if THEY submit the contact form, or
 * if they used a unique link you personally shared with them.
 */

// Make TypeScript aware of the gtag function injected by GA4.
declare global {
  interface Window {
    gtag?: (...args: unknown[]) => void;
  }
}

const SOURCE_KEY = 'portfolio_visitor_source';

/**
 * Reads ?source= from the URL on first load and stores it in
 * localStorage. Call this once when the app mounts (ClickTracker does this).
 */
export function captureSource(): void {
  if (typeof window === 'undefined') return;
  const params = new URLSearchParams(window.location.search);
  const source = params.get('source');
  if (source) {
    // A fresh source in the URL always overwrites the stored one.
    window.localStorage.setItem(SOURCE_KEY, source);
  }
}

/** Returns the stored visitor source, or 'direct' if none. */
export function getSource(): string {
  if (typeof window === 'undefined') return 'direct';
  return window.localStorage.getItem(SOURCE_KEY) || 'direct';
}

/**
 * trackEvent — the single function to call for every tracked action.
 *
 * @param eventName     e.g. "resume_download_click"
 * @param eventCategory e.g. "engagement", "navigation", "form"
 * @param eventLabel    e.g. "Hero Resume Button"
 */
export function trackEvent(
  eventName: string,
  eventCategory: string,
  eventLabel: string
): void {
  if (typeof window === 'undefined') return;

  const source = getSource();
  const pagePath = window.location.pathname;

  // 1) Google Analytics 4
  if (typeof window.gtag === 'function') {
    window.gtag('event', eventName, {
      event_category: eventCategory,
      event_label: eventLabel,
      source,
      page_path: pagePath,
    });
  }

  // 2) Our own Supabase log via the API route.
  //    keepalive lets the request finish even if the page navigates away
  //    (important for outbound link clicks like GitHub / LinkedIn).
  try {
    fetch('/api/track-click', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      keepalive: true,
      body: JSON.stringify({
        event_name: eventName,
        event_category: eventCategory,
        event_label: eventLabel,
        page_path: pagePath,
        source,
      }),
    }).catch(() => {
      /* silently ignore — tracking must never break the UI */
    });
  } catch {
    /* ignore */
  }
}
