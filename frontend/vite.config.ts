import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The build lands in bucketio/web, which is what `bucketio serve` mounts at "/",
// and what Vercel promotes to its CDN from the FastAPI StaticFiles mount.
// `npm run dev` proxies the API to a locally running server on 127.0.0.1:8080.
export default defineConfig({
  plugins: [react()],
  base: "/",
  build: {
    outDir: "../bucketio/web",
    emptyOutDir: true,
    assetsDir: "assets",
    target: "es2022",
  },
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8080",
      "/health": "http://127.0.0.1:8080",
    },
  },
});