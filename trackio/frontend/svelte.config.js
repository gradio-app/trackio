import { vitePreprocess } from "@sveltejs/vite-plugin-svelte";

export default {
  preprocess: vitePreprocess(),
  onwarn: (warning, handler) => {
    if (warning.code === "a11y_label_has_associated_control") return;
    handler(warning);
  },
};
