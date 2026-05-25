/**
 * Sanity schema: Profile
 * A single document holding hero / about / contact info.
 * (Create just ONE document of this type.)
 */
import { defineType, defineField } from 'sanity';

export default defineType({
  name: 'profile',
  title: 'Profile',
  type: 'document',
  fields: [
    defineField({
      name: 'name',
      title: 'Name',
      type: 'string',
    }),
    defineField({
      name: 'headline',
      title: 'Hero Headline',
      type: 'string',
    }),
    defineField({
      name: 'subheadline',
      title: 'Hero Subheadline',
      type: 'string',
    }),
    defineField({
      name: 'intro',
      title: 'Short Intro',
      type: 'text',
      rows: 3,
    }),
    defineField({
      name: 'about',
      title: 'About Text',
      type: 'text',
      rows: 6,
    }),
    defineField({ name: 'email', title: 'Email', type: 'string' }),
    defineField({ name: 'github', title: 'GitHub URL', type: 'url' }),
    defineField({ name: 'linkedin', title: 'LinkedIn URL', type: 'url' }),
    defineField({ name: 'location', title: 'Location', type: 'string' }),
  ],
});
