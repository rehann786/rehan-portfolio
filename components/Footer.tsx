'use client';
/**
 * components/Footer.tsx
 * --------------------------------------------------------------
 * Site footer with tracked social/email links.
 */
import { profile } from '@/lib/data';
import { trackEvent } from '@/lib/analytics';

export default function Footer() {
  const year = new Date().getFullYear();

  return (
    <footer className="border-t border-steel/40 bg-coal">
      <div className="max-w-6xl mx-auto px-6 py-10 flex flex-col sm:flex-row items-center justify-between gap-6">
        {/* Left — name */}
        <div className="text-center sm:text-left">
          <div className="font-display font-semibold">
            Rehan Ali Mohammed<span className="text-gold">.</span>
          </div>
          <p className="text-xs text-ash mt-1">
            Data Science · Python · AI/ML · Automation
          </p>
        </div>

        {/* Right — links */}
        <div className="flex items-center gap-5 text-sm">
          <a
            href={profile.github}
            target="_blank"
            rel="noopener noreferrer"
            onClick={() =>
              trackEvent('github_click', 'navigation', 'Footer GitHub')
            }
            className="text-ash hover:text-gold transition-colors"
          >
            GitHub
          </a>
          <a
            href={profile.linkedin}
            target="_blank"
            rel="noopener noreferrer"
            onClick={() =>
              trackEvent('linkedin_click', 'navigation', 'Footer LinkedIn')
            }
            className="text-ash hover:text-gold transition-colors"
          >
            LinkedIn
          </a>
          <a
            href={`mailto:${profile.email}`}
            onClick={() =>
              trackEvent('email_click', 'navigation', 'Footer Email')
            }
            className="text-ash hover:text-gold transition-colors"
          >
            Email
          </a>
        </div>
      </div>

      <div className="border-t border-steel/40 py-4">
        <p className="text-center text-xs text-ash">
          © {year} Rehan Ali Mohammed. Built with Next.js & Tailwind CSS.
        </p>
      </div>
    </footer>
  );
}
