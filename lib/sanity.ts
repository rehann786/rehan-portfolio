/**
 * lib/sanity.ts
 * --------------------------------------------------------------
 * Sanity CMS client + typed fetch helpers.
 *
 * Every helper falls back to the static content in lib/data.ts if:
 *   - Sanity env vars are not set, OR
 *   - the query returns nothing / throws.
 * This means the website works fully even before Sanity is configured.
 */
import { createClient } from '@sanity/client';
import {
  projects as fallbackProjects,
  skillGroups as fallbackSkills,
  experiences as fallbackExperiences,
  Project,
  SkillGroup,
  Experience,
} from './data';

const projectId = process.env.NEXT_PUBLIC_SANITY_PROJECT_ID;
const dataset = process.env.NEXT_PUBLIC_SANITY_DATASET || 'production';

const isConfigured = Boolean(projectId);

const client = isConfigured
  ? createClient({
      projectId: projectId as string,
      dataset,
      apiVersion: '2024-01-01',
      useCdn: true, // fast, cached reads
    })
  : null;

/** Fetch projects from Sanity, ordered, with static fallback. */
export async function getProjects(): Promise<Project[]> {
  if (!client) return fallbackProjects;
  try {
    const data = await client.fetch<Project[]>(
      `*[_type == "project"] | order(order asc) {
        title, description, tech, github, demo
      }`
    );
    return data && data.length > 0 ? data : fallbackProjects;
  } catch {
    return fallbackProjects;
  }
}

/** Fetch skill groups from Sanity with static fallback. */
export async function getSkills(): Promise<SkillGroup[]> {
  if (!client) return fallbackSkills;
  try {
    const data = await client.fetch<SkillGroup[]>(
      `*[_type == "skill"] | order(order asc) {
        category, skills
      }`
    );
    return data && data.length > 0 ? data : fallbackSkills;
  } catch {
    return fallbackSkills;
  }
}

/** Fetch experience entries from Sanity with static fallback. */
export async function getExperiences(): Promise<Experience[]> {
  if (!client) return fallbackExperiences;
  try {
    const data = await client.fetch<Experience[]>(
      `*[_type == "experience"] | order(order asc) {
        role, organization, period, description
      }`
    );
    return data && data.length > 0 ? data : fallbackExperiences;
  } catch {
    return fallbackExperiences;
  }
}
