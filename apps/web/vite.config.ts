import { defineConfig, type ProxyOptions } from 'vite';
import react from '@vitejs/plugin-react';

const apiProxy: ProxyOptions = {
  target: 'http://127.0.0.1:8001',
  changeOrigin: true,
  // SSE: make sure event-stream responses are never buffered by the dev proxy.
  configure: (proxy) => {
    proxy.on('proxyRes', (proxyRes) => {
      const contentType = String(proxyRes.headers['content-type'] ?? '');
      if (contentType.includes('text/event-stream')) {
        proxyRes.headers['cache-control'] = 'no-cache';
        proxyRes.headers['x-accel-buffering'] = 'no';
      }
    });
  },
};

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': apiProxy,
    },
  },
});
