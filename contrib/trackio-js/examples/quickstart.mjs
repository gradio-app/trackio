// quickstart.mjs
import { TrackioClient } from "../src/client.js";

// Best-effort wait for API to be up
async function waitForAPI(base, ms = 5000) {
  const start = Date.now();
  const url = base.replace(/\/+$/, "") + "/api/projects";
  while (Date.now() - start < ms) {
    try {
      const r = await fetch(url);
      if (r.ok) return true;
    } catch {}
    await new Promise(r => setTimeout(r, 120));
  }
  return false;
}

function env(name, fallback) {
  return process.env[name] && process.env[name].length ? process.env[name] : fallback;
}

async function main() {
  const base = env("TRACKIO_SERVER_URL", "http://127.0.0.1:7860").replace(/\/+$/, "");
  const project = env("TRACKIO_PROJECT", "js-quickstart");
  const run = env("TRACKIO_RUN", "js-run-1");

  console.log("* Waiting for Trackio server at:", base);
  const up = await waitForAPI(base, 5000);
  if (!up) {
    console.error("! Trackio API not reachable at", base);
    process.exit(1);
  }
  console.log("* Trackio REST detected at:", `${base}/api/projects`);

  // Configure client
  const c = new TrackioClient()
    .withBaseURL(base)
    .withProject(project)
    .withRun(run);

  // Log a few sample points (omit timestamp arg; client will not send it)
  c.log({ loss: 0.90, acc: 0.60 }, 0);
  c.log({ loss: 0.75, acc: 0.68 }, 1);
  c.log({ loss: 0.62, acc: 0.73 }, 2);

  console.log("* Flushing logs...");
  await c.flush();

  // Verify: list runs and fetch logs
  const runsRes = await fetch(`${base}/api/runs/${encodeURIComponent(project)}`);
  const runs = await runsRes.json();
  console.log("* Runs for project:", project, runs);

  const logsRes = await fetch(
    `${base}/api/logs/${encodeURIComponent(project)}/${encodeURIComponent(run)}`
  );
  const logs = await logsRes.json();
  console.log(`* Retrieved ${logs.length} log rows. First row:`, logs[0]);

  console.log("* Done. Open the dashboard:");
  console.log("  ", `${base}/?selected_project=${encodeURIComponent(project)}&selected_run=${encodeURIComponent(run)}`);
}

main().catch(err => {
  console.error(err);
  process.exit(1);
});