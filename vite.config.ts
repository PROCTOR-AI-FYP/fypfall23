import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { defineConfig, loadEnv } from 'vite'
import path from 'path'
import { resolveDevProxyTarget } from './src/lib/api-origin.ts'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, import.meta.dirname, '')
  const proxyTarget = resolveDevProxyTarget(env.VITE_API_BASE_URL, env.PROCTORAI_API_PROXY_TARGET)
  return {
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': path.resolve(import.meta.dirname, './src'),
    },
  },
  server: {
    proxy: {
      '/api': { target: proxyTarget,changeOrigin:false },
      '/socket.io': { target: proxyTarget,ws:true,changeOrigin:false },
    },
    watch: {
      ignored: ['**/.backups/**', '**/venv/**', '**/.venv/**',
        '**/ai-engine/models/**', '**/ai-engine/validation-output/**',
        '**/ai-engine/checkpoints/**', '**/ai-engine/.runtime/**'],
    },
  },
  }
})
