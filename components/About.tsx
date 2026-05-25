/**
 * components/About.tsx
 * --------------------------------------------------------------
 * About section. Server component — receives the about text as a prop
 * (sourced from Sanity with a static fallback in page.tsx).
 */
import { profile } from '@/lib/data';

export default function About({ about }: { about?: string }) {
  const text = about || profile.about;

  return (
    <section id="about" className="py-24 border-t border-steel/40">
      <div className="max-w-6xl mx-auto px-6">
        <p className="section-kicker">01 / About</p>
        <h2 className="mt-3 font-display font-bold text-3xl sm:text-4xl">
          Turning data into{' '}
          <span className="text-gold">usable tools</span>
        </h2>

        <div className="mt-10 grid md:grid-cols-3 gap-8">
          {/* Bio text */}
          <div className="md:col-span-2">
            <p className="text-ash leading-relaxed text-lg">{text}</p>
          </div>

          {/* Quick facts card */}
          <aside className="bg-coal border border-steel/60 rounded-xl p-6">
            <h3 className="font-display font-semibold text-gold mb-4">
              Quick Facts
            </h3>
            <ul className="space-y-3 text-sm">
              <li className="flex justify-between gap-4">
                <span className="text-ash">Program</span>
                <span className="text-chalk text-right">
                  MS Data Science
                </span>
              </li>
              <li className="flex justify-between gap-4">
                <span className="text-ash">University</span>
                <span className="text-chalk text-right">Wichita State</span>
              </li>
              <li className="flex justify-between gap-4">
                <span className="text-ash">Currently at</span>
                <span className="text-chalk text-right">NIAR AVET</span>
              </li>
              <li className="flex justify-between gap-4">
                <span className="text-ash">Focus</span>
                <span className="text-chalk text-right">
                  AI/ML, Automation
                </span>
              </li>
              <li className="flex justify-between gap-4">
                <span className="text-ash">Location</span>
                <span className="text-chalk text-right">
                  {profile.location}
                </span>
              </li>
            </ul>
          </aside>
        </div>
      </div>
    </section>
  );
}
