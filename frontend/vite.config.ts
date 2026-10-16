import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// `npm run dev` serves the UI on :5173 and forwards /api to a running review server.
const backend = process.env.FILTER_LAB_BACKEND ?? "http://127.0.0.1:9101";

export default defineConfig({
  plugins: [react()],
  // review.py swaps this placeholder for a new nonce on every page view (see its CSP header).
  html: { cspNonce: "__CSP_NONCE__" },
  build: {
    // The CSP allows images and fonts from 'self' only, so never inline assets as data: URLs.
    assetsInlineLimit: 0,
    chunkSizeWarningLimit: 900,
  },
  server: {
    proxy: {
      "/api": {
        target: backend,
        changeOrigin: true,
        // review.py only accepts changes whose Origin is the host it serves.
        configure: (proxy) => proxy.on("proxyReq", (request) => request.setHeader("origin", backend)),
      },
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    css: false,
  },
});
