/**
 * components/Skills.tsx
 * --------------------------------------------------------------
 * Skills section — grouped skill categories rendered as cards
 * with badge-style chips. Server component; data passed as prop.
 */
import { SkillGroup } from '@/lib/data';

export default function Skills({ groups }: { groups: SkillGroup[] }) {
  return (
    <section id="skills" className="py-24 border-t border-steel/40 bg-coal/30">
      <div className="max-w-6xl mx-auto px-6">
        <p className="section-kicker">02 / Skills</p>
        <h2 className="mt-3 font-display font-bold text-3xl sm:text-4xl">
          Tools I work with
        </h2>
        <p className="mt-3 text-ash max-w-xl">
          A practical stack spanning data science, software development, and
          engineering-focused tooling.
        </p>

        <div className="mt-10 grid sm:grid-cols-2 lg:grid-cols-3 gap-5">
          {groups.map((group) => (
            <div
              key={group.category}
              className="bg-coal border border-steel/60 rounded-xl p-6 hover:border-gold/50 transition-colors"
            >
              <h3 className="font-display font-semibold text-chalk mb-4 flex items-center gap-2">
                <span className="w-1.5 h-5 bg-gold rounded-full" />
                {group.category}
              </h3>
              <div className="flex flex-wrap gap-2">
                {group.skills.map((skill) => (
                  <span
                    key={skill}
                    className="px-2.5 py-1 rounded-md bg-slate text-xs text-ash border border-steel/60 hover:text-gold hover:border-gold/50 transition-colors"
                  >
                    {skill}
                  </span>
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
