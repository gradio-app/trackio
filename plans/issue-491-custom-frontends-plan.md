## Issue 491 Plan: Custom Frontends for Trackio

### Goal

Allow users to point Trackio at a custom static frontend directory so they can vibecode their own dashboard UI on top of the existing Trackio HTTP API.

This should work for:

- `trackio show --frontend /path/to/frontend`
- `trackio.show(frontend_dir="/path/to/frontend")`
- account-wide persistent config so all Trackio commands use the custom frontend by default
- Hugging Face Spaces deploys and static Space deploys

If a specified frontend directory is missing or invalid, Trackio should fall back to a shipped starter template rather than failing.

### Decisions

- The custom frontend fully replaces the bundled Svelte dashboard when selected.
- Persistent config affects all Trackio projects and all relevant commands.
- When config-driven behavior is in effect, Trackio prints a message showing which frontend is being used and how to reset it.
- The starter template is purely static HTML/CSS/JS and talks directly to the Trackio API.
- Publicity/demo themes live in a separate repo folder and are not used by runtime code.

### Implementation

1. Add a shared frontend resolver.
   - Resolve frontend from explicit arg, then env var, then persistent config, then bundled frontend.
   - Validate directories by checking for `index.html`.
   - Fall back to the starter template when an explicitly selected frontend is invalid.

2. Add persistent config support.
   - Store Trackio user config in a small JSON file under the Trackio user home.
   - Add CLI commands to set, inspect, and unset the default frontend.

3. Refactor frontend serving.
   - Make frontend serving generic so it can serve any static directory, not only the bundled Svelte `dist`.
   - Preserve existing API/backend behavior.

4. Wire custom frontend selection into public interfaces.
   - Add `frontend_dir` to `trackio.show()`.
   - Add `--frontend` to `trackio show`, `trackio sync`, and `trackio freeze`.

5. Reuse the same frontend resolution for deploy.
   - Gradio Spaces deploys should upload the selected frontend and launch Trackio against it.
   - Static Spaces deploys should upload the selected frontend as the static site root.

6. Ship a starter template.
   - Include a minimal static frontend with `index.html`, `styles.css`, and `app.js`.
   - Keep the code simple and LLM-editable.

7. Add demo themes.
   - Add four visually distinct example custom frontends plus screenshots in a repo-only examples folder.

8. Add tests and docs.
   - Cover resolution precedence, fallback behavior, CLI config, and deploy integration.
   - Update README and docs for launch/environment/deploy flows.
