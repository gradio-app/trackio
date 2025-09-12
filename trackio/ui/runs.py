import gradio as gr
import pandas as pd

try:
    from trackio.sqlite_storage import SQLiteStorage
except ImportError:
    from sqlite_storage import SQLiteStorage


with gr.Blocks() as run_page:
    runs_table = gr.Dataframe(
        value=pd.DataFrame(SQLiteStorage.get_all_run_configs("default")),
        interactive=False,
    )
