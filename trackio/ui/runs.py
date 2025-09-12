import gradio as gr

try:
    import trackio.utils as utils
    from trackio.file_storage import FileStorage
    from trackio.media import TrackioImage, TrackioVideo
    from trackio.sqlite_storage import SQLiteStorage
    from trackio.table import Table
    from trackio.typehints import LogEntry, UploadEntry
except:  # noqa: E722
    import utils
    from file_storage import FileStorage
    from media import TrackioImage, TrackioVideo
    from sqlite_storage import SQLiteStorage
    from table import Table
    from typehints import LogEntry, UploadEntry


with gr.Blocks() as run_page:
    gr.Textbox(label="Runs")
