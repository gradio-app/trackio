// quickstart.mjs
// No imports needed — Node 18+ has global fetch

function env(name, fallback) {
  return process.env[name] && process.env[name].length
    ? process.env[name]
    : fallback;
}

async function main() {
  const base = env("TRACKIO_SERVER_URL", "http://127.0.0.1:7860").replace(/\/+$/, "");
  const hfToken = env("HF_TOKEN", "");
  if (!hfToken) {
    console.error("HF_TOKEN is required (write token for your Space)");
    process.exit(1);
  }

  console.log("* Using Trackio server:", base);

  // Trackio schema for bulk_log
  const logs = [
    {
      project: "js-quickstart",
      run: "js-run-1",
      metrics: { loss: 0.90, acc: 0.60 },
      step: 0,
      config: null,
    },
    {
      project: "js-quickstart",
      run: "js-run-1",
      metrics: { loss: 0.75, acc: 0.68 },
      step: 1,
      config: null,
    },
    {
      project: "js-quickstart",
      run: "js-run-1",
      metrics: { loss: 0.62, acc: 0.73 },
      step: 2,
      config: null,
    },
  ];

  const payload = {
    data: [logs, hfToken],
  };

  const url = `${base}/gradio_api/call/bulk_log`;

  console.log("* POST", url);
  const resp = await fetch(url, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
  });

  console.log("status:", resp.status, resp.statusText);
  const text = await resp.text();
  console.log(text);

  console.log("\nOpen your dashboard:");
  console.log(
    `  ${base}/?selected_project=js-quickstart&selected_run=js-run-1`
  );
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});