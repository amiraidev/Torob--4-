import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
export default defineConfig({
  plugins: [react()],
  server: {host:'0.0.0.0', port:4173, strictPort:false, allowedHosts:['terminal.local'], proxy:{'/api':{target:process.env.DJANGO_API_URL || 'http://127.0.0.1:8000',changeOrigin:true}}},
  build: {chunkSizeWarningLimit:750}
});
