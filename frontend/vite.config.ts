import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    host: true, // reachable from outside the docker container
    port: 5173,
    proxy: {
      // In compose BACKEND_ORIGIN=http://backend:8000; on the host it falls
      // back to localhost:8000 (the backend port is published in dev).
      '/api': {
        target: process.env.BACKEND_ORIGIN ?? 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})
