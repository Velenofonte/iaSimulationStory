import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    host: true, // 0.0.0.0 — raggiungibile da cellulare in LAN
    port: 5173,
    proxy: {
      // Stesso origin della pagina → niente 127.0.0.1 sul telefono
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
});
