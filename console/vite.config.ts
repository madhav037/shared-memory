import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The console and the API share one origin everywhere: Caddy does it in production, this proxy does it here.
const server = process.env.SHARED_MEMORY_SERVER ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  // Bound to 127.0.0.1 so the address the tests and the browser use is the one Vite listens on.
  server: { host: "127.0.0.1", port: 5173, proxy: { "/api": server } },
  preview: { host: "127.0.0.1", port: 4173, proxy: { "/api": server } },
});
