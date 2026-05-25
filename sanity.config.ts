/**
 * sanity.config.ts
 * --------------------------------------------------------------
 * Sanity Studio configuration.
 *
 * You can run the Studio in two ways (see README):
 *   A) As a separate Sanity project created with `npm create sanity@latest`
 *   B) Embedded — by adding the Studio route to this Next.js app.
 *
 * Either way, this config defines your content schemas. The schema
 * files live in /sanity/schemaTypes.
 */
import { defineConfig } from 'sanity';
import { structureTool } from 'sanity/structure';
import { schemaTypes } from './sanity/schemaTypes';

export default defineConfig({
  name: 'rehan-portfolio',
  title: 'Rehan Portfolio CMS',

  // These come from your .env.local
  projectId: process.env.NEXT_PUBLIC_SANITY_PROJECT_ID || 'your-project-id',
  dataset: process.env.NEXT_PUBLIC_SANITY_DATASET || 'production',

  plugins: [structureTool()],

  schema: {
    types: schemaTypes,
  },
});
