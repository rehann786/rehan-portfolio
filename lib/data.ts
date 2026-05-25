/**
 * lib/data.ts
 * --------------------------------------------------------------
 * Static fallback content.
 * The site fetches projects / skills / experience from Sanity CMS,
 * but if Sanity is not configured yet, these values are used so the
 * website still renders correctly. Each Sanity helper in lib/sanity.ts
 * falls back to the exports here when no CMS data is returned.
 */

export type Project = {
  title: string;
  description: string;
  tech: string[];
  github?: string;
  demo?: string;
};

export type SkillGroup = {
  category: string;
  skills: string[];
};

export type Experience = {
  role: string;
  organization: string;
  period: string;
  description: string;
};

// ---- Profile -------------------------------------------------
export const profile = {
  name: 'Rehan Ali Mohammed',
  headline: 'Rehan Ali Mohammed',
  subheadline:
    'Data Science Graduate Student | Python Developer | AI/ML & Engineering Automation',
  intro:
    'I build practical data-driven tools using Python, machine learning, SQL, Power BI, and modern software development workflows. My work focuses on automation, analytics, engineering applications, and intelligent decision-support systems.',
  about:
    "I am a Master's in Data Science student at Wichita State University with hands-on experience in Python development, machine learning, data analytics, dashboard design, automation, and engineering-focused software tools. I currently work at NIAR AVET, where I apply data science and software engineering to real aerospace and materials problems. I enjoy turning messy data into clean, usable tools — from desktop applications to dashboards to extraction pipelines.",
  email: 'rehanali71813@gmail.com', // TODO: replace with your real email
  github: 'https://github.com/your-username', // TODO: replace
  linkedin: 'https://linkedin.com/in/your-handle', // TODO: replace
  location: 'Wichita, Kansas, USA',
};

// ---- Skills --------------------------------------------------
export const skillGroups: SkillGroup[] = [
  {
    category: 'Programming',
    skills: ['Python', 'SQL', 'JavaScript', 'TypeScript', 'HTML', 'CSS'],
  },
  {
    category: 'Data Science / AI',
    skills: [
      'Machine Learning',
      'Data Cleaning',
      'Feature Engineering',
      'Model Evaluation',
      'Regression',
      'Classification',
      'NLP Basics',
    ],
  },
  {
    category: 'Libraries',
    skills: ['Pandas', 'NumPy', 'Scikit-learn', 'Matplotlib', 'OpenPyXL'],
  },
  {
    category: 'Visualization',
    skills: ['Power BI', 'Excel', 'Dashboards', 'DAX Basics'],
  },
  {
    category: 'Software Development',
    skills: ['Git', 'GitHub', 'VS Code', 'APIs', 'Automation', 'File Processing'],
  },
  {
    category: 'Desktop Apps',
    skills: ['Tkinter', 'ttk', 'GUI Design', 'CSV/Excel Integration'],
  },
  {
    category: 'Cloud / Web',
    skills: ['Next.js', 'Vercel', 'Supabase', 'Sanity CMS'],
  },
];

// ---- Projects ------------------------------------------------
export const projects: Project[] = [
  {
    title: 'MMPDS Material Selection GUI',
    description:
      'A Python desktop application for browsing engineering material data, filtering materials, and generating property cards from structured CSV datasets.',
    tech: ['Python', 'Tkinter', 'ttk', 'Pandas', 'CSV', 'GUI Design'],
    github: '',
    demo: '',
  },
  {
    title: 'MAT024 + GISSMO Material Card Tool',
    description:
      'A material modeling tool focused on MAT024 and GISSMO-related engineering calculations, curve behavior, and property-card generation.',
    tech: ['Python', 'Engineering Calculations', 'Data Processing', 'GUI'],
    github: '',
    demo: '',
  },
  {
    title: 'SEC Schedule 2 / 10-K Extraction Project',
    description:
      'A data extraction workflow for identifying companies with Schedule 2 data from SEC 10-K filings, including CIK, company name, and GVKEY matching.',
    tech: ['Python', 'SEC Filings', 'Data Extraction', 'Pandas', 'CSV'],
    github: '',
    demo: '',
  },
  {
    title: 'Power BI Healthcare Performance Dashboard',
    description:
      'An interactive healthcare analytics dashboard with KPIs, slicers, classic visuals, and business insights.',
    tech: ['Power BI', 'DAX', 'Data Visualization', 'Dashboard Design'],
    github: '',
    demo: '',
  },
  {
    title: 'Appointment Scheduler Website',
    description:
      'A web-based appointment booking concept for academic scheduling with student booking, admin access, and email notification flow.',
    tech: ['Web Development', 'UI/UX', 'Scheduling Logic'],
    github: '',
    demo: '',
  },
  {
    title: 'AI Research Dashboard',
    description:
      'A dashboard-style project for organizing and presenting AI research insights, model comparisons, and project outputs.',
    tech: ['Python', 'AI/ML', 'Dashboard Design'],
    github: '',
    demo: '',
  },
];

// ---- Experience ----------------------------------------------
export const experiences: Experience[] = [
  {
    role: 'Graduate Student, Data Science',
    organization: 'Wichita State University',
    period: '2024 — Present',
    description:
      "Pursuing a Master's in Data Science with coursework in machine learning, optimization, business intelligence, and analytics. Building applied projects across the full data pipeline.",
  },
  {
    role: 'Research / Developer Role',
    organization: 'NIAR AVET',
    period: '2024 — Present',
    description:
      'Working on aerospace materials tooling and AI/ML infrastructure — developing Python applications, data extraction workflows, and engineering-focused software tools.',
  },
  {
    role: 'Teaching Assistant / Academic Support',
    organization: 'Wichita State University',
    period: '2024',
    description:
      'Supported coursework and students in data science and programming topics. (Update this placeholder with specific course details.)',
  },
];

// ---- Resume --------------------------------------------------
export const resume = {
  // Put your resume PDF in the /public folder and update this path.
  fileUrl: '/resume.pdf',
  lastUpdated: 'May 2026',
};
