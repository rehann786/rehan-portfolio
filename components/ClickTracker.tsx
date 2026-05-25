'use client';
/**
 * components/ClickTracker.tsx
 * --------------------------------------------------------------
 * Tiny client component that runs once on mount and stores the
 * ?source= URL parameter (e.g. ?source=linkedin) into localStorage.
 * From then on, every trackEvent() call attaches that source.
 *
 * Renders nothing visible.
 */
import { useEffect } from 'react';
import { captureSource } from '@/lib/analytics';

export default function ClickTracker() {
  useEffect(() => {
    captureSource();
  }, []);

  return null;
}
