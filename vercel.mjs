import { createVercelConfig } from './scripts/vercel-config.mjs';

// Each Vercel environment supplies its API origin; localhost still uses Vite.
export const config = createVercelConfig(process.env);
