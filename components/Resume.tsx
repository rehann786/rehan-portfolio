'use client';
/**
 * components/Resume.tsx
 * --------------------------------------------------------------
 * Resume section with an embedded PDF preview placeholder and a
 * Download button that fires the "resume_download_click" event.
 *
 * To enable the preview: place your resume PDF at /public/resume.pdf
 * (or update resume.fileUrl in lib/data.ts).
 */
import { resume } from '@/lib/data';
import { trackEvent } from '@/lib/analytics';

export default function Resume() {
  return (
    <section id="resume" className="py-24 border-t border-steel/40">
      <div className="max-w-6xl mx-auto px-6">
        <p className="section-kicker">05 / Resume</p>
        <h2 className="mt-3 font-display font-bold text-3xl sm:text-4xl">
          My resume
        </h2>
        <p className="mt-3 text-ash">
          Last updated {resume.lastUpdated}.
        </p>

        <div className="mt-10 grid md:grid-cols-3 gap-6">
          {/* Embedded preview (placeholder until resume.pdf exists) */}
          <div className="md:col-span-2 bg-coal border border-steel/60 rounded-xl overflow-hidden">
            <div className="aspect-[8.5/11] w-full bg-slate grid place-items-center">
              {/*
                When /public/resume.pdf exists, the <object> below renders
                a live preview. Browsers that cannot embed PDFs show the
                fallback message.
              */}
              <object
                data={resume.fileUrl}
                type="application/pdf"
                className="w-full h-full"
              >
                <div className="text-center p-8">
                  <div className="font-mono text-gold text-sm mb-2">
                    [ resume preview ]
                  </div>
                  <p className="text-ash text-sm max-w-xs">
                    Add your resume PDF at{' '}
                    <code className="text-chalk">/public/resume.pdf</code> to
                    show a live preview here.
                  </p>
                </div>
              </object>
            </div>
          </div>

          {/* Download panel */}
          <aside className="bg-coal border border-steel/60 rounded-xl p-6 flex flex-col">
            <h3 className="font-display font-semibold text-gold">
              Download
            </h3>
            <p className="mt-2 text-sm text-ash leading-relaxed flex-1">
              Grab a PDF copy of my full resume — education, experience,
              projects, and skills.
            </p>

            {/* This button MUST fire resume_download_click */}
            <a
              href={resume.fileUrl}
              download
              onClick={() =>
                trackEvent(
                  'resume_download_click',
                  'engagement',
                  'Resume Section Download'
                )
              }
              className="mt-5 px-5 py-3 rounded-lg bg-gold text-ink font-semibold text-center hover:bg-goldDark transition-colors"
            >
              Download Resume (PDF)
            </a>
          </aside>
        </div>
      </div>
    </section>
  );
}
