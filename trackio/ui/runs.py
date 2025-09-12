import gradio as gr
import pandas as pd

try:
    from trackio.sqlite_storage import SQLiteStorage
except ImportError:
    from sqlite_storage import SQLiteStorage


def get_runs_data(project: str) -> pd.DataFrame:
    """Get all runs with their configuration data for a project."""
    if not project:
        return pd.DataFrame()
    
    runs = SQLiteStorage.get_runs(project)
    if not runs:
        return pd.DataFrame()
    
    # Get all configs for the project
    configs = SQLiteStorage.get_all_run_configs(project)
    
    runs_data = []
    
    for run_name in runs:
        logs = SQLiteStorage.get_logs(project, run_name)
        if not logs:
            continue
            
        # Get the first log entry for timing info
        first_log = logs[0]
        last_log = logs[-1]
        
        # Calculate runtime
        if len(logs) > 1:
            start_time = pd.to_datetime(first_log.get("timestamp", ""))
            end_time = pd.to_datetime(last_log.get("timestamp", ""))
            runtime_seconds = (end_time - start_time).total_seconds()
            if runtime_seconds < 60:
                runtime = f"{int(runtime_seconds)}s"
            elif runtime_seconds < 3600:
                runtime = f"{int(runtime_seconds // 60)}m {int(runtime_seconds % 60)}s"
            else:
                hours = int(runtime_seconds // 3600)
                minutes = int((runtime_seconds % 3600) // 60)
                runtime = f"{hours}h {minutes}m"
        else:
            runtime = "0s"
        
        # Format creation time
        created_time = first_log.get("timestamp", "")
        if created_time:
            try:
                created_dt = pd.to_datetime(created_time)
                now = pd.Timestamp.now()
                time_diff = now - created_dt
                if time_diff.days > 0:
                    created = f"{time_diff.days}d ago"
                elif time_diff.seconds > 3600:
                    created = f"{time_diff.seconds // 3600}h ago"
                elif time_diff.seconds > 60:
                    created = f"{time_diff.seconds // 60}m ago"
                else:
                    created = "just now"
            except Exception:
                created = created_time
        else:
            created = ""
        
        # Extract basic run info
        run_info = {
            "Name": run_name,
            "State": "Finished",  # Default state
            "Notes": "",
            "Created": created,
            "Runtime": runtime,
            "Sweep": "",
        }
        
        # Add configuration data if available
        if run_name in configs:
            config = configs[run_name]
            for key, value in config.items():
                if isinstance(value, (int, float, str)):
                    # Format numeric values nicely
                    if isinstance(value, float):
                        if value < 0.001:
                            run_info[key] = f"{value:.2e}"
                        else:
                            run_info[key] = f"{value:.5f}".rstrip('0').rstrip('.')
                    else:
                        run_info[key] = str(value)
        
        runs_data.append(run_info)
    
    if not runs_data:
        return pd.DataFrame()
    
    # Convert to DataFrame
    df = pd.DataFrame(runs_data)
    
    # Sort by creation time (most recent first)
    if "Created" in df.columns:
        df = df.sort_values("Created", ascending=False)
    
    return df


def update_runs_table(project: str) -> pd.DataFrame:
    """Update the runs table when project changes."""
    return get_runs_data(project)


def get_projects() -> list[str]:
    """Get list of available projects."""
    return SQLiteStorage.get_projects()


def load_projects() -> gr.Dropdown:
    """Load projects into dropdown."""
    projects = get_projects()
    return gr.Dropdown(choices=projects, value=projects[0] if projects else None)


with gr.Blocks(
    title="Trackio - Runs",
    theme=gr.themes.Soft(),
    css="""
    .runs-container {
        padding: 20px;
    }
    .runs-header {
        margin-bottom: 20px;
    }
    .runs-controls {
        margin-bottom: 20px;
        display: flex;
        gap: 10px;
        align-items: center;
    }
    .runs-table {
        border: 1px solid #e0e0e0;
        border-radius: 8px;
        overflow: hidden;
    }
    """
) as run_page:
    
    with gr.Column(elem_classes=["runs-container"]):
        # Header
        with gr.Row(elem_classes=["runs-header"]):
            gr.Markdown("# Runs", elem_id="runs-title")
        
        # Controls
        with gr.Row(elem_classes=["runs-controls"]):
            project_dropdown = gr.Dropdown(
                label="Project",
                choices=[],
                value=None,
                interactive=True,
                scale=2
            )
            search_box = gr.Textbox(
                label="Search runs",
                placeholder="Search runs...",
                interactive=True,
                scale=3
            )
            filter_btn = gr.Button("Filter", scale=1)
            group_btn = gr.Button("Group", scale=1)
            sort_btn = gr.Button("Sort", scale=1)
            columns_btn = gr.Button("Columns", scale=1)
        
        # Runs table
        with gr.Row(elem_classes=["runs-table"]):
            runs_table = gr.Dataframe(
                headers=["Name", "State", "Notes", "Created", "Runtime", "Sweep"],
                datatype=["str", "str", "str", "str", "str", "str"],
                interactive=False,
                wrap=True,
                value=pd.DataFrame(),
                elem_id="runs-table"
            )
    
    # Load projects on page load
    run_page.load(
        fn=load_projects,
        outputs=[project_dropdown]
    )
    
    # Update runs table when project changes
    project_dropdown.change(
        fn=update_runs_table,
        inputs=[project_dropdown],
        outputs=[runs_table]
    )
