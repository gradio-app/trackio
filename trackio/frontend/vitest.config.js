import { svelte } from "@sveltejs/vite-plugin-svelte";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [svelte()],
  resolve: { conditions: ["browser"] },
  test: {
    projects: [
      { extends: true, test: { name: "unit", environment: "node", include: ["src/lib/**/*.test.js"] } },
      { extends: true, test: { name: "components", environment: "jsdom", include: ["src/pages/**/*.test.js"] } },
    ],
  },
});
