import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { VitePWA } from 'vite-plugin-pwa'
import path from 'path'

const apiProxy = {
  '/api': 'http://localhost:8080',
}

export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      registerType: 'autoUpdate',
      manifest: {
        name: 'Seed 42',
        short_name: 'Seed 42',
        lang: 'ru',
        start_url: '/',
        display: 'standalone',
        background_color: '#ffffff',
        theme_color: '#6d4aff',
      },
      workbox: {
        navigateFallbackDenylist: [/^\/api/],
      },
    }),
  ],

  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    }
  },

  css: {
    modules: {
      localsConvention: 'camelCaseOnly',
    },
  },

  server: {
    proxy: apiProxy,
  },

  preview: {
    proxy: apiProxy,
  },
})
