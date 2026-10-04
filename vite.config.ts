import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { defineConfig } from 'vite'
import path from 'path'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': path.resolve(import.meta.dirname, './src'),
    },
  },
  server: {
    proxy: {
      '/api': { target: process.env.PROCTORAI_API_PROXY_TARGET || 'http://127.0.0.1:8000',changeOrigin:false },
      '/socket.io': { target: process.env.PROCTORAI_API_PROXY_TARGET || 'http://127.0.0.1:8000',ws:true,changeOrigin:false },
    },
    watch: {
      ignored: ['**/.backups/**', '**/venv/**', '**/.venv/**',
        '**/ai-engine/models/**', '**/ai-engine/validation-output/**',
        '**/ai-engine/checkpoints/**', '**/ai-engine/.runtime/**'],
    },
  },
})
