import gradio as gr
import pandas as pd

try:
    import trackio.utils as utils
    from trackio.sqlite_storage import SQLiteStorage
except ImportError:
    import utils
    from sqlite_storage import SQLiteStorage


with gr.Blocks() as run_page:
    with gr.Sidebar(open=False) as sidebar:
        logo = gr.Markdown(
            f"""
                <img src='/gradio_api/file={utils.TRACKIO_LOGO_DIR}/trackio_logo_type_light_transparent.png' width='80%' class='logo-light'>
                <img src='/gradio_api/file={utils.TRACKIO_LOGO_DIR}/trackio_logo_type_dark_transparent.png' width='80%' class='logo-dark'>            
            """
        )
        project_dd = gr.Dropdown(label="Project", allow_custom_value=True)

    gr.on(
        [run_page.load],
        fn=get_projects,
        outputs=project_dd,
        show_progress="hidden",
        queue=False,
        api_name=False,
    )

    runs_table = gr.Dataframe(
        value=pd.DataFrame(SQLiteStorage.get_all_run_configs("default")),
        interactive=False,
    )
