import { TrackioClient } from "../src/client.js";

// Optional: wait for Trackio to be up by pinging /api/projects (best-effort)
async function waitForAPI(base, ms = 5000) {
  const start = Date.now();
  while (Date.now() - start < ms) {
    try {
      const r = await fetch(base.replace(/\/+$/, "") + "/api/projects");
      if (r.ok) return true;
    } catch {}
    await new Promise(r => setTimeout(r, 100));
  }
  return false;
}

async function main() {
  const base = process.env.TRACKIO_SERVER_URL || "http://127.0.0.1:7860";
  console.log("* Waiting for Trackio server at:", base);
  const ok = await waitForAPI(base, 5000);
  if (!ok) {
    console.error("Trackio API not reachable at", base);
    console.error("Start it with:\n  export TRACKIO_SHOW_API=1\n  python -c \"import trackio; trackio.init(project='js-quickstart', embed=False); import time; time.sleep(9999)\"");
    process.exit(1);
  }
  console.log("* Trackio REST detected.");

  const c = new TrackioClient()
    .withBaseURL(base)
    .withProject("js-quickstart")
    .withRun("js-run-1");

  // log a couple points
  c.log({ loss: 0.5, acc: 0.8 }, 0, "");
  c.log({ loss: 0.4, acc: 0.82 }, 1, "");

  console.log("* Flushing logs...");
  await c.flush();
  console.log("* Done. Open the Trackio dashboard:");
  console.log("  ", `${base}/?selected_project=js-quickstart`);
}

main().catch(err => {
  console.error(err);
  process.exit(1);
});