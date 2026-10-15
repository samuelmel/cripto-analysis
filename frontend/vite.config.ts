import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import { positionsApi } from "./server/positionsApi";

export default defineConfig({
  plugins: [react(), tailwindcss(), positionsApi()],
});
