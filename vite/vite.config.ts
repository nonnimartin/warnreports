import { reactRouter } from '@react-router/dev/vite'
import { defineConfig } from 'vite'

const API_PROXY_TARGET = process.env.API_PROXY_TARGET || 'http://127.0.0.1:8000'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [reactRouter()],
  server: {
    proxy: {
      '/api/v0': {
        target: API_PROXY_TARGET,
        changeOrigin: true,
        secure: false,
      },
      '/feed/atom': {
        target: API_PROXY_TARGET,
        changeOrigin: true,
        secure: false,
      },
      '/feed/rss': {
        target: API_PROXY_TARGET,
        changeOrigin: true,
        secure: false,
      },
    },
  },
})