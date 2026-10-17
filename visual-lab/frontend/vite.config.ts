import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Visual lab dev server on 5174; API proxied to the visual-lab backend on 8100.
export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5174,
    strictPort: true,
    proxy: { "/api": "http://127.0.0.1:8100" },
  },
  preview: { host: "127.0.0.1", port: 5174, strictPort: true, proxy: { "/api": "http://127.0.0.1:8100" } },
  build: { chunkSizeWarningLimit: 2000 },
});
