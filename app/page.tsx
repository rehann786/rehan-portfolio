/**
 * app/page.tsx
 * --------------------------------------------------------------
 * Home page. This is a Server Component — it fetches content from
 * Sanity at request time (with static fallback baked into the
 * sanity helpers) and passes it down to the section components.
 */
import Navbar from '@/components/Navbar';
import Hero from '@/components/Hero';
import About from '@/components/About';
import Skills from '@/components/Skills';
import Experience from '@/components/Experience';
import Projects from '@/components/Projects';
import Resume from '@/components/Resume';
import Contact from '@/components/Contact';
import Footer from '@/components/Footer';
import { getProjects, getSkills, getExperiences } from '@/lib/sanity';

// Revalidate the page every 60 seconds so CMS edits show up quickly.
export const revalidate = 60;

export default async function HomePage() {
  // Fetch in parallel. Each helper falls back to static data if needed.
  const [projects, skills, experiences] = await Promise.all([
    getProjects(),
    getSkills(),
    getExperiences(),
  ]);

  return (
    <>
      <Navbar />
      <main>
        <Hero />
        <About />
        <Skills groups={skills} />
        <Experience experiences={experiences} />
        <Projects projects={projects} />
        <Resume />
        <Contact />
      </main>
      <Footer />
    </>
  );
}
