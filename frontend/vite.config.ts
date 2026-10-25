import { defineConfig } from 'vite'
import { fileURLToPath, URL } from 'node:url'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    host: true, // expose on the LAN for teammates
    proxy: {
      // Override with LITUBIK_API_TARGET when the backend runs on another port.
      '/api': process.env.LITUBIK_API_TARGET || 'http://localhost:8000',
    },
  },
})
