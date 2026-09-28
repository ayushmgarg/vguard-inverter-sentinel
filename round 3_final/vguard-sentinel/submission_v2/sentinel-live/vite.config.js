import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { viteSingleFile } from 'vite-plugin-singlefile';

// Single self-contained HTML (dist/index.html) — opens offline by double-click at the venue.
export default defineConfig({
  plugins: [react(), viteSingleFile()],
  base: './',
  build: { assetsInlineLimit: 100000000, chunkSizeWarningLimit: 8000, cssCodeSplit: false },
});
