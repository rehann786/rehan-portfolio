'use client';
/**
 * components/Hero.tsx
 * --------------------------------------------------------------
 * Landing hero section with headline, intro, and CTA buttons.
 * The Resume / GitHub / LinkedIn / Contact buttons all fire
 * tracked events via trackEvent().
 */
import { trackEvent } from '@/lib/analytics';
import { profile, resume } from '@/lib/data';

export default function Hero() {
  return (
    <section
      id="home"
      className="relative min-h-screen flex items-center bg-grid overflow-hidden"
    >
      {/* Soft glow accents for depth */}
      <div className="pointer-events-none absolute -top-32 -right-32 w-96 h-96 rounded-full bg-gold/10 blur-3xl" />
      <div className="pointer-events-none absolute bottom-0 left-0 w-80 h-80 rounded-full bg-gold/5 blur-3xl" />

      <div className="max-w-6xl mx-auto px-6 pt-28 pb-20 w-full">
        {/* Status pill */}
        <div
          className="inline-flex items-center gap-2 px-3 py-1 rounded-full border border-steel bg-coal/60 text-xs font-mono text-ash mb-8 animate-fade-up"
          style={{ animationDelay: '0ms' }}
        >
          <span className="w-2 h-2 rounded-full bg-gold animate-pulse" />
          Open to internships & data science roles
        </div>

        {/* Headline */}
        <h1
          className="font-display font-bold tracking-tight text-5xl sm:text-6xl lg:text-7xl leading-[1.05] animate-fade-up"
          style={{ animationDelay: '80ms' }}
        >
          {profile.headline}
        </h1>

        {/* Subheadline */}
        <p
          className="mt-5 text-lg sm:text-xl text-gold font-medium animate-fade-up"
          style={{ animationDelay: '160ms' }}
        >
          {profile.subheadline}
        </p>

        {/* Intro */}
        <p
          className="mt-6 max-w-2xl text-ash leading-relaxed animate-fade-up"
          style={{ animationDelay: '240ms' }}
        >
          {profile.intro}
        </p>

        {/* Buttons */}
        <div
          className="mt-9 flex flex-wrap gap-3 animate-fade-up"
          style={{ animationDelay: '320ms' }}
        >
          {/* Download Resume — fires resume_download_click */}
          <a
            href={resume.fileUrl}
            download
            onClick={() =>
              trackEvent(
                'resume_download_click',
                'engagement',
                'Hero Download Resume'
              )
            }
            className="px-6 py-3 rounded-lg bg-gold text-ink font-semibold hover:bg-goldDark transition-colors"
          >
            Download Resume
          </a>

          {/* View Projects — simple scroll */}
          <a
            href="#projects"
            className="px-6 py-3 rounded-lg border border-steel text-chalk font-semibold hover:border-gold hover:text-gold transition-colors"
          >
            View Projects
          </a>

          {/* GitHub */}
          <a
            href={profile.github}
            target="_blank"
            rel="noopener noreferrer"
            onClick={() =>
              trackEvent('github_click', 'navigation', 'Hero GitHub')
            }
            className="px-6 py-3 rounded-lg border border-steel text-chalk font-semibold hover:border-gold hover:text-gold transition-colors"
          >
            GitHub
          </a>

          {/* LinkedIn */}
          <a
            href={profile.linkedin}
            target="_blank"
            rel="noopener noreferrer"
            onClick={() =>
              trackEvent('linkedin_click', 'navigation', 'Hero LinkedIn')
            }
            className="px-6 py-3 rounded-lg border border-steel text-chalk font-semibold hover:border-gold hover:text-gold transition-colors"
          >
            LinkedIn
          </a>

          {/* Contact Me */}
          <a
            href="#contact"
            className="px-6 py-3 rounded-lg border border-steel text-chalk font-semibold hover:border-gold hover:text-gold transition-colors"
          >
            Contact Me
          </a>
        </div>

        {/* Quick stats strip */}
        <div
          className="mt-16 grid grid-cols-2 sm:grid-cols-4 gap-px bg-steel/60 rounded-xl overflow-hidden border border-steel/60 animate-fade-up"
          style={{ animationDelay: '400ms' }}
        >
          {[
            { k: 'MS', v: 'Data Science' },
            { k: '6+', v: 'Featured Projects' },
            { k: 'Python', v: 'Core Stack' },
            { k: 'NIAR', v: 'AVET Experience' },
          ].map((s) => (
            <div key={s.v} className="bg-coal px-5 py-5">
              <div className="font-display text-2xl font-bold text-gold">
                {s.k}
              </div>
              <div className="text-xs text-ash mt-1">{s.v}</div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
