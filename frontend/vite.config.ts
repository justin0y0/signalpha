import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': {
        // In the compose network the API is `backend`; a local preview points this at
        // the live site instead (VITE_API_TARGET=https://signalpha.app).
        target: process.env.VITE_API_TARGET ?? 'http://backend:8000',
        secure: true,
        changeOrigin: true,
      },
    },
  },
  build: {
    // Everything shipped as one 920 KB chunk, so a visitor landing on Contact paid
    // for recharts, framer-motion and d3 before seeing a word. Tolerable until the
    // WebGL work — three.js alone is ~150 KB and belongs only on the pages that
    // actually render a scene.
    rollupOptions: {
      output: {
        manualChunks(id: string) {
          if (!id.includes('node_modules')) return
          if (id.includes('three')) return 'gfx'
          if (id.includes('recharts') || id.includes('d3')) return 'charts'
          if (id.includes('framer-motion')) return 'motion'
          if (id.includes('react-router')) return 'router'
          return 'vendor'
        },
      },
    },
    chunkSizeWarningLimit: 700,
  },
})
