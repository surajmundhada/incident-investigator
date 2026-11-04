import { defineConfig } from "vite";

// Same-origin requests; the browser never receives database/provider credentials.
const proxy = {
  "/api": { target: "http://127.0.0.1:8001" },
  "/healthz": { target: "http://127.0.0.1:8001" },
  "/readyz": { target: "http://127.0.0.1:8001" },
};
export default defineConfig({
  server: { port: 5173, strictPort: true, proxy },
  preview: { port: 5173, strictPort: true, proxy },
});
