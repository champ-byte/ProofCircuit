import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// The backend stays the only holder of secrets; the browser talks to it through this proxy.
const backend = process.env.PROOFCIRCUIT_BACKEND ?? 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [react()],
  server: {
    host: '127.0.0.1',
    port: 5173,
    proxy: { '/api': backend },
  },
})
