# Trackio as an API and MCP Server

The Trackio dashboard can be configured to run as both an HTTP API server and an MCP (Model Context Protocol) server, allowing external tools and applications to programmatically interact with your experiment tracking data, or for you to be able to "chat with your experiment data" in natural language using ChatGPT, Claude, Deepseek, or various LLMs that support MCPs. This makes Trackio an ideal choice for LLM agents running autonomous ML experiments, as they can seamlessly log metrics and query experiment results.

## Setup

Install the optional MCP dependency, then enable the MCP server when launching the Trackio dashboard. You can do this a few different ways:

```bash
pip install "trackio[mcp]"
```

### Option 1: CLI Command
```bash
trackio show --mcp-server
```

### Option 2: Python Function
```python
import trackio
trackio.show(mcp_server=True)
```

### Option 3: Environment Variable
```bash
export GRADIO_MCP_SERVER=True
trackio show
```

When MCP server mode is enabled, Trackio:
- Mounts a streamable-HTTP MCP server alongside the dashboard
- Exposes read-only project/run/metric inspection tools to MCP clients
- Exposes a small set of mutation tools (delete/rename/sync) gated by a write token

## API Usage

Trackio exposes each MCP tool as a plain HTTP endpoint at `POST /api/{tool_name}`. The body is JSON; pass arguments as `{"kwargs": {...}}`, `{"args": [...]}`, or simply as a flat `{"name": value}` object.

<hfoptions id="api-mcp-server">
<hfoption id="Python">

```python
import httpx

base = "http://127.0.0.1:7860"

projects = httpx.post(f"{base}/api/get_all_projects").json()["data"]
print("Projects:", projects)

runs = httpx.post(
    f"{base}/api/get_runs_for_project",
    json={"project": "my-project"},
).json()["data"]
print("Runs:", runs)

values = httpx.post(
    f"{base}/api/get_metric_values",
    json={"project": "my-project", "run": "run-1", "metric_name": "loss"},
).json()["data"]
print("Loss values:", values)
```

</hfoption>
<hfoption id="JavaScript">

```javascript
const base = "http://127.0.0.1:7860";

async function call(name, payload = {}) {
  const res = await fetch(`${base}/api/${name}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return (await res.json()).data;
}

console.log("Projects:", await call("get_all_projects"));
console.log("Runs:", await call("get_runs_for_project", { project: "my-project" }));
console.log("Loss:", await call("get_metric_values", {
  project: "my-project",
  run: "run-1",
  metric_name: "loss",
}));
```

</hfoption>
<hfoption id="Bash">

```bash
# Get all projects
curl -s -X POST http://127.0.0.1:7860/api/get_all_projects \
  -H "Content-Type: application/json" -d '{}'

# Get runs for a project
curl -s -X POST http://127.0.0.1:7860/api/get_runs_for_project \
  -H "Content-Type: application/json" \
  -d '{"project": "my-project"}'

# Get values for a metric
curl -s -X POST http://127.0.0.1:7860/api/get_metric_values \
  -H "Content-Type: application/json" \
  -d '{"project": "my-project", "run": "run-1", "metric_name": "loss"}'
```

</hfoption>
</hfoptions>

## MCP Usage

When running as an MCP server, Trackio exposes its tools at a single streamable-HTTP endpoint that MCP-compatible clients (Claude Desktop, Claude Code, etc.) can connect to.

### MCP Server URL

The MCP server is available at:
```txt
http://127.0.0.1:7860/mcp/
```

When deployed to a Hugging Face Space, the URL is `https://<your-space>.hf.space/mcp/`.

### Available MCP Tools

Read tools:

1. **get_all_projects** – List all Trackio projects on this server.
2. **get_runs_for_project** – List runs for a given project.
3. **get_metrics_for_run** – List metric names recorded for a run.
4. **get_metric_values** – Fetch metric values for a run, optionally around a step or time.
5. **get_project_summary** – Summary metadata for a project.
6. **get_run_summary** – Summary metadata for a run.
7. **get_system_metrics_for_run** – List system metric names recorded for a run.
8. **get_system_logs** – Fetch system metric logs for a run.
9. **get_snapshot** – Fetch a single snapshot around a step or timestamp.
10. **get_logs** – Fetch metric logs for a run.
11. **get_alerts** – Fetch alerts for a project, optionally filtered by run or level.
12. **get_settings** – Return dashboard settings and asset configuration.

Mutation tools (require write access — see below):

13. **delete_run** – Delete a run.
14. **rename_run** – Rename a run.
15. **trigger_sync** – Trigger an export/sync pass to Hugging Face.

### Write Access for Mutation Tools

Mutation tools are gated:

- **Local dashboard:** pass the `write_token` argument. The token is printed in the terminal when you run `trackio show` (it's also embedded as `?write_token=...` in the dashboard URL printed at startup). For example:
  ```json
  {"project": "my-project", "run": "run-1", "write_token": "<token from startup output>"}
  ```
- **Hugging Face Spaces:** pass an `hf_token` argument with write access to the Space's repo. The local `write_token` is not used in this case.

Read tools never require a token.

### MCP Client Configuration

To add Trackio to clients that support streamable-HTTP MCP servers, use a config like:

```json
{
  "mcpServers": {
    "trackio": {
      "url": "http://127.0.0.1:7860/mcp/"
    }
  }
}
```
