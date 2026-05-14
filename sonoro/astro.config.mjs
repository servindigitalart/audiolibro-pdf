import { defineConfig } from 'astro/config';
import react from '@astrojs/react';
import tailwind from '@astrojs/tailwind';
import vercel from '@astrojs/vercel/serverless';
import path from 'path';

export default defineConfig({
  output: 'server',

  adapter: vercel({
    webAnalytics: { enabled: true },
  }),

  integrations: [
    react(),
    tailwind({ applyBaseStyles: false }),
  ],

  vite: {
    resolve: {
      alias: {
        '@': path.resolve('./src'),
      },
    },
  },
});
