import { fileURLToPath } from 'node:url'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

const contracts = fileURLToPath(new URL('../contracts', import.meta.url))

export default defineConfig({
  plugins: [react()],
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
    include: ['src/**/*.test.{ts,tsx}'],
  },
})
