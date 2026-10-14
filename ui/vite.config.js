import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Dev server proxies the API to a local backend (uvicorn on :7300).
export default defineConfig({
  plugins: [react()],
  server: { proxy: { '/api': 'http://127.0.0.1:7300' } },
  build: { outDir: 'dist', emptyOutDir: true, sourcemap: false },
});
