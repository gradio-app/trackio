# Python API for Managing Runs

Trackio provides a Python API class (`trackio.Api()`) that allows you to programmatically manage runs in your projects. This API is similar to `wandb.Api()` and provides methods to delete runs, move runs between projects, and access run information.

**Note:** This is different from [Trackio as an API Server](api_mcp_server.md), which runs the Trackio dashboard as a web server with API endpoints. The Python API (`trackio.Api()`) is a client-side interface for managing runs in your local Trackio database.

## Basic Usage

```python
import trackio

# Initialize the API
api = trackio.Api()

# Get all runs in a project
runs = api.runs("my_project")

# Access individual runs
for run in runs:
    print(f"Run: {run.name}, Project: {run.project}")
    print(f"Config: {run.config}")

# Or access by index
first_run = runs[0]
```

## Deleting Runs

```python
api = trackio.Api()
runs = api.runs("my_project")

# Delete a specific run
run = runs[0]
success = run.delete()  # Returns True if successful
```

## Moving Runs Between Projects

```python
api = trackio.Api()
runs = api.runs("source_project")

# Move a run to a different project
run = runs[0]
success = run.move("target_project")  # Returns True if successful

# After moving, the run object's project is updated
print(run.project)  # "target_project"
```

When you move a run, all associated data is transferred:
- All metrics and logs
- Run configuration
- System metrics
- Media files (images, videos, audio)

The run is completely removed from the source project and added to the target project.

## API Reference

### Api

Main entry point for the Trackio Python API.

```python
api = trackio.Api()
```

#### Methods

- **`runs(project: str) -> Runs`**: Returns a collection of runs for the specified project. Raises `ValueError` if the project doesn't exist.

### Runs

A collection of runs that supports iteration and indexing.

```python
runs = api.runs("my_project")
len(runs)  # Number of runs
runs[0]    # First run
for run in runs:  # Iterate over runs
    ...
```

### Run

Represents a single run in a project.

#### Properties

- **`id`**: The run name (same as `name`)
- **`name`**: The run name
- **`project`**: The project this run belongs to
- **`config`**: The run's configuration dictionary (lazy-loaded)

#### Methods

- **`delete() -> bool`**: Deletes the run from its project. Returns `True` if successful, `False` otherwise.
- **`move(new_project: str) -> bool`**: Moves the run to a different project. Returns `True` if successful, `False` otherwise. Updates the run's `project` property after a successful move.

## Examples

### List all runs across projects

```python
import trackio
from trackio.sqlite_storage import SQLiteStorage

api = trackio.Api()

# Get all projects
projects = SQLiteStorage.get_projects()

# List runs in each project
for project in projects:
    print(f"\nProject: {project}")
    runs = api.runs(project)
    for run in runs:
        print(f"  - {run.name}")
```

### Clean up old runs

```python
api = trackio.Api()
runs = api.runs("my_project")

# Delete runs older than a certain date
from datetime import datetime
cutoff_date = datetime(2024, 1, 1)

for run in runs:
    if run.config and "_Created" in run.config:
        created = datetime.fromisoformat(run.config["_Created"])
        if created < cutoff_date:
            run.delete()
            print(f"Deleted old run: {run.name}")
```

### Organize runs by moving them

```python
api = trackio.Api()

# Move all runs from "experiments" to "archive"
source_runs = api.runs("experiments")
for run in source_runs:
    run.move("archive")
    print(f"Moved {run.name} to archive")
```

