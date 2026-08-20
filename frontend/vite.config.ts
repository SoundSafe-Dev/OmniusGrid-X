import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      // react-plotly.js peers on full plotly.js; serve the bundled dist build.
      'plotly.js/dist/plotly': 'plotly.js-dist-min',
      'plotly.js': 'plotly.js-dist-min',
    },
  },
  server: {
    host: '0.0.0.0',
    port: 3000,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    // Was `true`, which shipped a ~13.6MB .map alongside the bundle. There is no
    // error-tracking pipeline consuming maps, so don't generate/ship them. If
    // one is added later, switch to 'hidden' and upload the maps out-of-band.
    sourcemap: false,
    rollupOptions: {
      output: {
        // Split the heavy vendors into their own chunks so they load on demand
        // (with the lazy routes that use them) instead of inflating the main
        // entry chunk. plotly.js-dist-min and leaflet in particular are large
        // and only used by a few chart/map routes.
        manualChunks(id) {
          if (!id.includes('node_modules')) return undefined
          if (id.includes('plotly')) return 'plotly'
          if (id.includes('leaflet')) return 'leaflet'
          if (id.includes('recharts') || id.includes('/d3-') || id.includes('/d3/')) {
            return 'charts'
          }
          // REACT IS DELIBERATELY NOT SPLIT OUT (FS-766).
          //
          // This used to return 'react-vendor' for react/react-dom/scheduler, which put
          // React in one chunk and everything that depends on it — react-query, router,
          // zustand — in `vendor`. The two chunks then imported each other:
          //
          //     react-vendor.js  imports -> vendor.js
          //     vendor.js        imports -> react-vendor.js
          //
          // ES modules resolve a cycle by handing out partially-initialised bindings, so
          // whichever evaluates first sees `undefined` for the other's exports. `vendor`
          // won, reached `React.createContext` inside react-query, and threw
          // "Cannot read properties of undefined (reading 'createContext')" — **a white
          // screen for the entire production bundle**, while `vite build` exited 0.
          //
          // Keeping React in the same chunk as its dependents removes the cycle. The point
          // of this function — keeping plotly, leaflet and the chart stack out of the entry
          // so they load with the routes that use them — is untouched, and those three have
          // no such cycle because nothing in `vendor` imports them.
          return 'vendor'
        },
      },
    },
  },
})
