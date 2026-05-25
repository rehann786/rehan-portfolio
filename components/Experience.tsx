/**
 * components/Experience.tsx
 * --------------------------------------------------------------
 * Experience section rendered as a vertical timeline.
 * Server component; data passed as prop.
 */
import { Experience as ExperienceType } from '@/lib/data';

export default function Experience({
  experiences,
}: {
  experiences: ExperienceType[];
}) {
  return (
    <section id="experience" className="py-24 border-t border-steel/40">
      <div className="max-w-6xl mx-auto px-6">
        <p className="section-kicker">03 / Experience</p>
        <h2 className="mt-3 font-display font-bold text-3xl sm:text-4xl">
          Where I&apos;ve worked
        </h2>

        <div className="mt-12 relative">
          {/* Vertical line */}
          <div className="absolute left-3 top-2 bottom-2 w-px bg-steel/70" />

          <div className="space-y-10">
            {experiences.map((exp, i) => (
              <div key={i} className="relative pl-12">
                {/* Timeline dot */}
                <span className="absolute left-0 top-1.5 w-6 h-6 rounded-full border-2 border-gold bg-ink grid place-items-center">
                  <span className="w-2 h-2 rounded-full bg-gold" />
                </span>

                <div className="bg-coal border border-steel/60 rounded-xl p-6 hover:border-gold/40 transition-colors">
                  <div className="flex flex-wrap items-baseline justify-between gap-2">
                    <h3 className="font-display font-semibold text-lg text-chalk">
                      {exp.role}
                    </h3>
                    <span className="text-xs font-mono text-gold">
                      {exp.period}
                    </span>
                  </div>
                  <p className="text-sm text-gold/90 mt-0.5">
                    {exp.organization}
                  </p>
                  <p className="mt-3 text-sm text-ash leading-relaxed">
                    {exp.description}
                  </p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}
