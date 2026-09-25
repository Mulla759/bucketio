import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The default build lands in bucketio/web, which is what `bucketio serve` mounts at "/".
// On Vercel the build must stay inside the frontend project (frontend/dist), so the output
// directory is conditional: Vercel's build runners set VERCEL=1, and `--mode vercel` opts in.
// `npm run dev` proxies the API to a locally running server on 127.0.0.1:8080.
export default defineConfig(({ mode }) => {
  const forVercel = !!process.env.VERCEL || mode === "vercel";

  return {
    plugins: [react()],
    base: "/",
    build: {
      outDir: forVercel ? "dist" : "../bucketio/web",
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
  };
});
