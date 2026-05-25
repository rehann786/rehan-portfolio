/**
 * sanity/schemaTypes/index.ts
 * Registers all schema types. Import this in your sanity.config.ts.
 */
import project from './project';
import skill from './skill';
import experience from './experience';
import profile from './profile';
import resume from './resume';

export const schemaTypes = [project, skill, experience, profile, resume];
