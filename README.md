# Rehan Ali Mohammed — Portfolio Website

A modern, dark-themed portfolio built with **Next.js (App Router) + TypeScript + Tailwind CSS**.
It includes a CMS for real-time content editing, visitor analytics, custom click tracking,
and a private admin dashboard.

---

## What's inside

| Feature | Tech |
|---|---|
| Framework | Next.js 14 (App Router), TypeScript |
| Styling | Tailwind CSS (dark, WSU black/gray/white/yellow theme) |
| Content editing | Sanity CMS (with static fallback data) |
| Visitor analytics | Google Analytics 4 + Vercel Analytics |
| Custom click tracking | Supabase (`portfolio_clicks` table) |
| Admin dashboard | `/admin` — password gated |
| Contact form | Formspree (or demo mode) |
| Hosting | Vercel |

---

## Table of contents

1. [Install Node.js](#1-install-nodejs)
2. [Run locally](#2-run-locally)
3. [Deploy to Vercel](#3-deploy-to-vercel)
4. [Connect GitHub](#4-connect-github)
5. [Environment variables](#5-environment-variables)
6. [Google Analytics 4 setup](#6-google-analytics-4-setup)
7. [Supabase setup](#7-supabase-setup)
8. [Create the Supabase table](#8-create-the-supabase-table)
9. [Sanity CMS setup](#9-sanity-cms-setup)
10. [Updating projects in real time](#10-updating-projects-in-real-time)
11. [Using unique tracking links](#11-using-unique-tracking-links)
12. [Privacy — what you can and cannot see](#12-privacy--what-you-can-and-cannot-see)

---

## 1. Install Node.js

1. Go to <https://nodejs.org>.
2. Download the **LTS** version (20.x or newer).
3. Run the installer (accept defaults).
4. Verify in a terminal / Command Prompt:

   ```cmd
   node -v
   npm -v
   ```

   Both should print version numbers.

---

## 2. Run locally

Open the project folder in **VS Code**, then open a terminal in it and run:

```cmd
npm install
npm run dev
```

Visit <http://localhost:3000> in your browser.

> The site works immediately even before you configure GA / Supabase / Sanity —
> it uses built-in fallback data from `lib/data.ts`.

To create a production build locally:

```cmd
npm run build
npm start
```

---

## 3. Deploy to Vercel

1. Create a free account at <https://vercel.com> (sign in with GitHub).
2. Click **Add New… → Project**.
3. Import your GitHub repo (see step 4 first if you haven't pushed it).
4. Vercel auto-detects Next.js — keep the defaults.
5. Before deploying, add your environment variables (see step 5) under
   **Settings → Environment Variables**.
6. Click **Deploy**. You'll get a live URL like `your-portfolio.vercel.app`.

Every future `git push` to your main branch automatically redeploys.

---

## 4. Connect GitHub

1. Create a repo at <https://github.com/new> (e.g. `portfolio`).
2. In your project folder terminal:

   ```cmd
   git init
   git add .
   git commit -m "Initial portfolio"
   git branch -M main
   git remote add origin https://github.com/YOUR-USERNAME/portfolio.git
   git push -u origin main
   ```

3. In Vercel, import this repo. Done — pushes now auto-deploy.

> `.gitignore` already excludes `.env.local`, so your secrets are never pushed.

---

## 5. Environment variables

Copy `.env.example` to `.env.local` and fill in the values:

```cmd
copy .env.example .env.local
```

| Variable | Purpose |
|---|---|
| `NEXT_PUBLIC_GA_ID` | Google Analytics 4 Measurement ID (`G-XXXXXXXXXX`) |
| `NEXT_PUBLIC_SUPABASE_URL` | Supabase project URL |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | Supabase anon/public key |
| `NEXT_PUBLIC_SANITY_PROJECT_ID` | Sanity project ID |
| `NEXT_PUBLIC_SANITY_DATASET` | Usually `production` |
| `ADMIN_PASSWORD` | Password for the `/admin` dashboard |
| `NEXT_PUBLIC_FORMSPREE_ENDPOINT` | Formspree form URL for the contact form |

**Add the same variables in Vercel** under Settings → Environment Variables, then redeploy.

> **About `ADMIN_PASSWORD`:** the admin page also reads `NEXT_PUBLIC_ADMIN_PASSWORD`.
> If you want the simple client-side gate to work on the deployed site, set
> `NEXT_PUBLIC_ADMIN_PASSWORD` to the same value. Be aware this exposes the password
> in the browser bundle — it is *obscurity*, not real security. For real security,
> use Supabase Auth (see step 7's note).

---

## 6. Google Analytics 4 setup

1. Go to <https://analytics.google.com> and create an account + property.
2. Choose **Web** as the platform and enter your site URL.
3. Open **Admin → Data Streams → your stream**.
4. Copy the **Measurement ID** (`G-XXXXXXXXXX`).
5. Put it in `.env.local` as `NEXT_PUBLIC_GA_ID` (and in Vercel).

GA4 automatically tracks page views. Custom button events (resume, GitHub, etc.)
are sent through the `trackEvent()` function and appear under
**Reports → Engagement → Events** (allow a few hours for data).

---

## 7. Supabase setup

Supabase stores your own copy of click events so you control the data.

1. Create a free account at <https://supabase.com>.
2. Click **New Project**, pick a name and a strong database password.
3. Once it's ready, go to **Settings → API** and copy:
   - **Project URL** → `NEXT_PUBLIC_SUPABASE_URL`
   - **anon public** key → `NEXT_PUBLIC_SUPABASE_ANON_KEY`
4. Add both to `.env.local` (and Vercel).

> **Security note:** the included setup allows public read of the click table so
> the simple `/admin` page can display data. No personal data is stored, so this
> is fine for a personal portfolio. For production-grade security, remove the
> "allow anon reads" policy in `supabase-setup.sql` and switch the admin page to
> **Supabase Auth** with Row Level Security.

---

## 8. Create the Supabase table

1. In Supabase, open **SQL Editor → New query**.
2. Open the file `supabase-setup.sql` from this project, copy its contents.
3. Paste into the SQL editor and click **Run**.

This creates the `portfolio_clicks` table with these columns:

| Column | Type |
|---|---|
| `id` | uuid (auto) |
| `event_name` | text |
| `event_category` | text |
| `event_label` | text |
| `page_path` | text |
| `source` | text |
| `created_at` | timestamptz (auto) |

Click events from the site are saved here via the `/api/track-click` route.

---

## 9. Sanity CMS setup

Sanity lets you edit projects/skills/experience without touching code.

**Create the Sanity project:**

```cmd
npm create sanity@latest
```

- Sign in / create a Sanity account.
- Choose **"Create new project"**, name it (e.g. `rehan-portfolio`).
- Use the **`production`** dataset.
- When asked for a template, you can pick "Clean project".

**Connect it to this site:**

1. From your Sanity project's dashboard, copy the **Project ID**.
2. Put it in `.env.local` as `NEXT_PUBLIC_SANITY_PROJECT_ID`
   and set `NEXT_PUBLIC_SANITY_DATASET=production`.
3. Copy the schema files from this project's `sanity/schemaTypes/` folder
   into your Sanity Studio's schema folder, and make sure
   `sanity.config.ts` registers `schemaTypes` (a ready config is included here).
4. Run the Studio:

   ```cmd
   npx sanity dev
   ```

   It opens at <http://localhost:3333>.

5. In the Studio, create documents: **Project**, **Skill Group**,
   **Experience**, **Profile**, **Resume**.

> Until you do this, the site shows the built-in fallback content from
> `lib/data.ts` — nothing breaks.

---

## 10. Updating projects in real time

Once Sanity is connected:

1. Open your Sanity Studio (`npx sanity dev`, or the deployed Studio URL).
2. Add or edit a **Project** document — title, description, tech tags,
   GitHub/demo links, and a display order number.
3. Click **Publish**.
4. The live site picks up changes within ~60 seconds
   (controlled by `export const revalidate = 60` in `app/page.tsx`).

No code changes, no redeploy needed.

---

## 11. Using unique tracking links

You can attribute traffic by adding a `?source=` parameter to your URL.
When someone opens the link, that source is stored in their browser and
attached to **every click event** they generate.

Examples — share a different link in each place:

```
https://your-portfolio.vercel.app/?source=linkedin
https://your-portfolio.vercel.app/?source=professor-rai
https://your-portfolio.vercel.app/?source=job-application
https://your-portfolio.vercel.app/?source=internship-email
```

In the `/admin` dashboard, the **Source** column shows which link a visitor used.
This is how you tell, for example, that a resume download came from a recruiter
email vs. from your LinkedIn profile.

---

## 12. Privacy — what you can and cannot see

**Important and intentional:**

- This portfolio **cannot automatically see the real name of every visitor.**
  Web analytics does not work that way.
- What you *can* see: number of visits, number of clicks, which buttons were
  clicked, which pages, timestamps, and the `source` tag from a tracking link.
- You can identify a specific person **only** when:
  1. **They submit the contact form** — they voluntarily give you their
     name and email, OR
  2. **They used a unique link you personally shared with them.** For example,
     if you send `?source=professor-rai` only to one professor, then activity
     tagged `professor-rai` is almost certainly that person — because *you*
     know who you gave that link to.

The `/api/track-click` route deliberately stores **no personal identity data** —
no names, no emails, no IP addresses. Only non-personal analytics fields.

---

## Tracked events reference

These event names are sent to both GA4 and Supabase:

| Event | Fired when |
|---|---|
| `resume_download_click` | Resume download button clicked |
| `github_click` | A GitHub link clicked |
| `linkedin_click` | A LinkedIn link clicked |
| `email_click` | An email link clicked |
| `project_demo_click` | A project's live demo opened |
| `project_github_click` | A project's code link opened |
| `contact_form_submit` | Contact form submitted |

---

## Project structure

```
portfolio/
├─ app/
│  ├─ layout.tsx            Root layout (fonts, analytics)
│  ├─ page.tsx              Home page (fetches Sanity data)
│  ├─ globals.css           Global styles
│  ├─ admin/page.tsx        Password-gated analytics dashboard
│  └─ api/track-click/route.ts   Saves click events to Supabase
├─ components/              Reusable UI components
├─ lib/
│  ├─ analytics.ts          trackEvent() + source capture
│  ├─ supabase.ts           Supabase client
│  ├─ sanity.ts             Sanity client + fetch helpers
│  └─ data.ts               Static fallback content
├─ sanity/schemaTypes/      Sanity CMS schemas
├─ supabase-setup.sql       SQL to create the click table
├─ sanity.config.ts         Sanity Studio config
└─ .env.example             Environment variable template
```

---

## Customizing your info

Edit `lib/data.ts` to set your real email, GitHub, and LinkedIn URLs
(look for the `TODO` comments). Put your resume PDF at `public/resume.pdf`.
Once Sanity is connected, projects/skills/experience are edited in the CMS instead.
