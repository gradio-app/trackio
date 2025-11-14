# Trackio as an API and MCP Server

The Trackio dashboard can be configured to run as both an API server and an MCP (Model Context Protocol) server, allowing external tools and applications to programmatically interact with your experiment tracking data, or for you to be able to "chat with your experiment data" in natural language using ChatGPT, Claude, Deepseek, or various LLMs that support MCPs.

## Setup

To enable API/MCP usage, start the MCP server when you launch the Trackio dashboard. You can do this a few different ways:

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

When MCP server mode is enabled, Trackio will:
- Enable the Gradio API endpoints
- Start an MCP server alongside the web dashboard
- Allow programmatic access to writing and reading experiment data 

## API Usage

Once your Trackio server is running in MCP mode, click on the **"Use via API or MCP"** link in the footer of the dashboard to see the complete API documentation with exact usage examples for all endpoints.

Here is example usage in Python, JS, Bash, and via MCP.

<hfoptions id="api-mcp-server">
<hfoption id="Python">

Using the [Gradio Python Client](https://www.gradio.app/guides/getting-started-with-the-python-client).

```python
from gradio_client import Client

# Connect to your Trackio instance
client = Client("http://127.0.0.1:7860/")

# Get all projects
result = client.predict(api_name="/get_all_projects")
print("Projects:", result)

# Get runs for a specific project
result = client.predict(
    project="my-project",
    api_name="/get_runs_for_project"
)
print("Runs:", result)

# Get metrics for a specific run
result = client.predict(
    project="my-project",
    run="run-1",
    api_name="/get_metrics_for_run"
)
print("Metrics:", result)

# Get metric values over time
result = client.predict(
    project="my-project",
    run="run-1",
    metric_name="loss",
    api_name="/get_metric_values"
)
print("Loss values:", result)

# Get project summary
result = client.predict(
    project="my-project",
    api_name="/get_project_summary"
)
print("Project summary:", result)

# Get run summary
result = client.predict(
    project="my-project",
    run="run-1",
    api_name="/get_run_summary"
)
print("Run summary:", result)
```

</hfoption>
<hfoption id="JavaScript">

Using the [Gradio JS Client](https://www.gradio.app/guides/getting-started-with-the-js-client).

```javascript
import { Client } from "@gradio/client";

const client = await Client.connect("http://127.0.0.1:7860/");

// Get all projects
const result = await client.predict("/get_all_projects", {});
console.log("Projects:", result.data);

// Get runs for a project
const result = await client.predict("/get_runs_for_project", {
    project: "my-project"
});
console.log("Runs:", result.data);

// Get metrics for a run
const result = await client.predict("/get_metrics_for_run", {
    project: "my-project",
    run: "run-1"
});
console.log("Metrics:", result.data);

// Get metric values
const result = await client.predict("/get_metric_values", {
    project: "my-project",
    run: "run-1",
    metric_name: "loss"
});
console.log("Values:", result.data);

// Get project summary
const result = await client.predict("/get_project_summary", {
    project: "my-project"
});
console.log("Project summary:", result.data);

// Get run summary
const result = await client.predict("/get_run_summary", {
    project: "my-project",
    run: "run-1"
});
console.log("Run summary:", result.data);
```

</hfoption>
<hfoption id="Bash">

Using standard `curl` commands.

```bash
# Get all projects
curl -X POST http://127.0.0.1:7860/gradio_api/call/get_all_projects -s -H "Content-Type: application/json" -d '{
    "data": []
}' \
| awk -F'"' '{ print $4}' \
| read EVENT_ID; curl -N http://127.0.0.1:7860/gradio_api/call/get_all_projects/$EVENT_ID

# Get runs for a project
curl -X POST http://127.0.0.1:7860/gradio_api/call/get_runs_for_project -s -H "Content-Type: application/json" -d '{
    "data": ["my-project"]
}' \
| awk -F'"' '{ print $4}' \
| read EVENT_ID; curl -N http://127.0.0.1:7860/gradio_api/call/get_runs_for_project/$EVENT_ID

# Get metrics for a run
curl -X POST http://127.0.0.1:7860/gradio_api/call/get_metrics_for_run -s -H "Content-Type: application/json" -d '{
    "data": ["my-project", "run-1"]
}' \
| awk -F'"' '{ print $4}' \
| read EVENT_ID; curl -N http://127.0.0.1:7860/gradio_api/call/get_metrics_for_run/$EVENT_ID

# Get metric values
curl -X POST http://127.0.0.1:7860/gradio_api/call/get_metric_values -s -H "Content-Type: application/json" -d '{
    "data": ["my-project", "run-1", "loss"]
}' \
| awk -F'"' '{ print $4}' \
| read EVENT_ID; curl -N http://127.0.0.1:7860/gradio_api/call/get_metric_values/$EVENT_ID

# Get project summary
curl -X POST http://127.0.0.1:7860/gradio_api/call/get_project_summary -s -H "Content-Type: application/json" -d '{
    "data": ["my-project"]
}' \
| awk -F'"' '{ print $4}' \
| read EVENT_ID; curl -N http://127.0.0.1:7860/gradio_api/call/get_project_summary/$EVENT_ID

# Get run summary
curl -X POST http://127.0.0.1:7860/gradio_api/call/get_run_summary -s -H "Content-Type: application/json" -d '{
    "data": ["my-project", "run-1"]
}' \
| awk -F'"' '{ print $4}' \
| read EVENT_ID; curl -N http://127.0.0.1:7860/gradio_api/call/get_run_summary/$EVENT_ID
```

</hfoption>
</hfoptions>

## MCP Usage

When running as an MCP server, Trackio exposes its API endpoints as MCP tools that can be used by MCP-compatible clients like Claude Code.

### MCP Server URL

The MCP server, using Streamble HTTP, is available (by default) at:
```txt
http://127.0.0.1:7860/gradio_api/mcp/
```

### Available MCP Tools

The main tools that are available when Trackio is running in MCP server mode are:

1. **get_all_projects** - Get all project names. Returns a list of project names.
2. **get_runs_for_project** - Get all runs for a given project. Returns a list of run names.
3. **get_metrics_for_run** - Get all metrics for a given project and run. Returns a list of metric names.
4. **get_metric_values** - Get all values for a specific metric in a project/run. Returns a list of dictionaries with timestamp, step, and value.
5. **get_project_summary** - Get a summary of a project including number of runs and recent activity. Returns: Dictionary with project summary information.
6. **get_run_summary** - Get a summary of a specific run including metrics and configuration. Returns: Dictionary with run summary information.
7. **bulk_log** - Log metrics data to Trackio. Each entry is a dictionary with project, run, metrics, and optionally step and config.
8. **upload_db_to_space** - Upload database file to Hugging Face Space. Requires file upload capability.
9. **bulk_upload_media** - Upload media files for experiments. Requires file upload capability.

### MCP Client Configuration

To add this MCP server to clients that support Streamable HTTP, add the following configuration to your MCP config:

```json
{
  "mcpServers": {
    "gradio": {
      "url": "http://127.0.0.1:7860/gradio_api/mcp/"
    },
    "upload_files_to_gradio": {
      "command": "uvx",
      "args": [
        "--from",
        "gradio[mcp]",
        "gradio",
        "upload-mcp",
        "http://127.0.0.1:7860/gradio_api/mcp/",
        "<UPLOAD_DIRECTORY>"
      ]
    }
  }
}
```

The `upload_files_to_gradio` tool uploads files from your local UPLOAD_DIRECTORY to the Gradio app, which is needed for file-based operations. This tool requires `uv` to be installed. You can omit this tool if you are not planning on using the file-based tools.



