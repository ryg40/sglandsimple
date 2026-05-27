import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import path from "node:path";

// Dev proxy sends /api to the FastAPI service so `npm run dev` works
// against a running stack. In production FastAPI serves the built SPA
// and these routes are same-origin, so the proxy is dev-only.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { "@": path.resolve(__dirname, "./src") },
  },
  server: {
    proxy: {
      "/api": { target: "http://localhost:5452", changeOrigin: true },
    },
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
    rollupOptions: {
      output: {
        // Split heavy, route-specific vendor libs into their own cacheable
        // chunks so the initial load doesn't pull React Flow / Recharts /
        // markdown+highlight.js. Combined with route-level React.lazy, a fresh
        // session downloads only the shell + landing route.
        manualChunks: {
          "vendor-react": ["react", "react-dom", "react-router-dom"],
          "vendor-flow": ["@xyflow/react"],
          "vendor-charts": ["recharts"],
          "vendor-markdown": ["react-markdown", "rehype-highlight", "highlight.js", "remark-gfm"],
          "vendor-query": ["@tanstack/react-query"],
        },
      },
    },
  },
});
