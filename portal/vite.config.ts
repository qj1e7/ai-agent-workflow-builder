import { fileURLToPath } from 'node:url'
import react from '@vitejs/plugin-react'
import type { Connect, Plugin } from 'vite'
import { defineConfig } from 'vitest/config'

const contracts = fileURLToPath(new URL('../contracts', import.meta.url))

function modeFromEnvironment(): Plugin {
  const mode = process.env['PORTAL_MODE']
  const serve = (server: { middlewares: Connect.Server }) => {
    if (!mode) return
    server.middlewares.use('/config.json', (_request, response) => {
      response.setHeader('Content-Type', 'application/json')
      response.end(JSON.stringify({ mode }))
    })
  }
  return { name: 'portal-mode-from-environment', configureServer: serve, configurePreviewServer: serve }
}

export default defineConfig({
  plugins: [react(), modeFromEnvironment()],
  resolve: { alias: { '@contracts': contracts } },
  server: {
    fs: { allow: ['.', contracts] },
    proxy: {
      '/api': { target: process.env['PLATFORM_API_URL'] ?? 'http://localhost:18000', changeOrigin: true },
    },
  },
  build: { target: 'es2022' },
  test: {
    environment: 'node',
    include: ['src/**/*.test.ts'],
  },
})
