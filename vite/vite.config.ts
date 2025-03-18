import react from '@vitejs/plugin-react-swc'
import { defineConfig } from 'vite'

const API_PROXY_TARGET = process.env.API_PROXY_TARGET || 'http://127.0.0.1:8000'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api/v0': {
        target: API_PROXY_TARGET,
        changeOrigin: true,
        secure: false,
      },
    },
  },
})