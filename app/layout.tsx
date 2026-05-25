/**
 * app/layout.tsx
 * --------------------------------------------------------------
 * Root layout. Loads fonts, global styles, and mounts the
 * analytics components (GA4 + Vercel Analytics + click source capture).
 */
import type { Metadata } from 'next';
import { Space_Grotesk, Sora, JetBrains_Mono } from 'next/font/google';
import { Analytics as VercelAnalytics } from '@vercel/analytics/react';
import './globals.css';
import Analytics from '@/components/Analytics';
import ClickTracker from '@/components/ClickTracker';

// Distinctive display font + clean body font + mono for technical accents.
const display = Space_Grotesk({
  subsets: ['latin'],
  variable: '--font-display',
  display: 'swap',
});
const body = Sora({
  subsets: ['latin'],
  variable: '--font-body',
  display: 'swap',
});
const mono = JetBrains_Mono({
  subsets: ['latin'],
  variable: '--font-mono',
  display: 'swap',
});

export const metadata: Metadata = {
  title: 'Rehan Ali Mohammed — Data Science & Python Developer',
  description:
    'Portfolio of Rehan Ali Mohammed — Data Science graduate student, Python developer, and AI/ML & engineering automation specialist.',
  keywords: [
    'Rehan Ali Mohammed',
    'Data Science',
    'Python Developer',
    'Machine Learning',
    'Wichita State University',
    'Portfolio',
  ],
  openGraph: {
    title: 'Rehan Ali Mohammed — Data Science & Python Developer',
    description:
      'Data Science graduate student | Python Developer | AI/ML & Engineering Automation',
    type: 'website',
  },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className={`${display.variable} ${body.variable} ${mono.variable}`}>
      <body className="font-body bg-ink text-chalk antialiased">
        {/* Google Analytics 4 — only loads if NEXT_PUBLIC_GA_ID is set */}
        <Analytics />
        {/* Captures ?source= UTM param into localStorage on first load */}
        <ClickTracker />
        {children}
        {/* Vercel Analytics — automatic page view tracking */}
        <VercelAnalytics />
      </body>
    </html>
  );
}
