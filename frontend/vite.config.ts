import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // The browser only ever talks to its own origin; Vite forwards /api to the backend.
    // Same-origin means no CORS configuration is needed on the API.
    proxy: {
      '/api': 'http://localhost:3000',
    },
  },
  test: {
    environment: 'jsdom',
    include: ['test/**/*.test.tsx'],
  },
});
