'use client';
/**
 * components/Projects.tsx
 * --------------------------------------------------------------
 * Projects section — a grid of project cards.
 * Each card's "Demo" and "GitHub" buttons fire tracked events.
 */
import { Project } from '@/lib/data';
import { trackEvent } from '@/lib/analytics';

export default function Projects({ projects }: { projects: Project[] }) {
  return (
    <section
      id="projects"
      className="py-24 border-t border-steel/40 bg-coal/30"
    >
      <div className="max-w-6xl mx-auto px-6">
        <p className="section-kicker">04 / Projects</p>
        <h2 className="mt-3 font-display font-bold text-3xl sm:text-4xl">
          Selected work
        </h2>
        <p className="mt-3 text-ash max-w-xl">
          Applied projects across desktop apps, data extraction, dashboards,
          and AI/ML.
        </p>

        <div className="mt-10 grid sm:grid-cols-2 lg:grid-cols-3 gap-5">
          {projects.map((project) => (
            <article
              key={project.title}
              className="group bg-coal border border-steel/60 rounded-xl p-6 flex flex-col hover:border-gold/50 hover:-translate-y-1 transition-all duration-300"
            >
              {/* Decorative index marker */}
              <div className="font-mono text-xs text-gold/70 mb-3">
                {'{ project }'}
              </div>

              <h3 className="font-display font-semibold text-lg text-chalk group-hover:text-gold transition-colors">
                {project.title}
              </h3>

              <p className="mt-2 text-sm text-ash leading-relaxed flex-1">
                {project.description}
              </p>

              {/* Tech tags */}
              <div className="mt-4 flex flex-wrap gap-1.5">
                {project.tech.map((t) => (
                  <span
                    key={t}
                    className="px-2 py-0.5 rounded bg-slate text-[11px] text-ash border border-steel/60"
                  >
                    {t}
                  </span>
                ))}
              </div>

              {/* Action buttons */}
              <div className="mt-5 flex gap-2">
                {project.demo ? (
                  <a
                    href={project.demo}
                    target="_blank"
                    rel="noopener noreferrer"
                    onClick={() =>
                      trackEvent(
                        'project_demo_click',
                        'project',
                        project.title
                      )
                    }
                    className="flex-1 text-center px-3 py-2 rounded-lg bg-gold text-ink text-sm font-semibold hover:bg-goldDark transition-colors"
                  >
                    Live Demo
                  </a>
                ) : (
                  <span className="flex-1 text-center px-3 py-2 rounded-lg bg-slate text-ash text-sm font-medium cursor-default">
                    Demo soon
                  </span>
                )}

                {project.github ? (
                  <a
                    href={project.github}
                    target="_blank"
                    rel="noopener noreferrer"
                    onClick={() =>
                      trackEvent(
                        'project_github_click',
                        'project',
                        project.title
                      )
                    }
                    className="flex-1 text-center px-3 py-2 rounded-lg border border-steel text-chalk text-sm font-semibold hover:border-gold hover:text-gold transition-colors"
                  >
                    Code
                  </a>
                ) : (
                  <span className="flex-1 text-center px-3 py-2 rounded-lg border border-steel/60 text-ash text-sm font-medium cursor-default">
                    Private
                  </span>
                )}
              </div>
            </article>
          ))}
        </div>
      </div>
    </section>
  );
}
