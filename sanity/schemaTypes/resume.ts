/**
 * Sanity schema: Resume
 * A single document holding the resume file and metadata.
 * Upload your resume PDF directly in the Sanity Studio.
 */
import { defineType, defineField } from 'sanity';

export default defineType({
  name: 'resume',
  title: 'Resume',
  type: 'document',
  fields: [
    defineField({
      name: 'title',
      title: 'Internal Title',
      type: 'string',
      initialValue: 'Resume',
    }),
    defineField({
      name: 'file',
      title: 'Resume PDF',
      type: 'file',
      options: { accept: '.pdf' },
    }),
    defineField({
      name: 'lastUpdated',
      title: 'Last Updated',
      type: 'string',
      description: 'e.g. "May 2026"',
    }),
  ],
});
