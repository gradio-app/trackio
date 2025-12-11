"""The Runs page for the Trackio UI."""

import gradio as gr

try:
    import trackio.utils as utils
    from trackio.sqlite_storage import SQLiteStorage
    from trackio.ui import fns
except ImportError:
    import utils
    from sqlite_storage import SQLiteStorage
    from ui import fns

RUN_DETAILS_TEMPLATE = """
## Run Details
* **Run Name:** `{run_name}`
* **Group:** `{group}`
* **Created:** {created} by {username}
"""

with gr.Blocks() as run_detail_page:
    with gr.Sidebar() as sidebar:
        logo_urls = utils.get_logo_urls()
        logo = gr.Markdown(
            f"""
                <img src='{logo_urls["light"]}' width='80%' class='logo-light'>
                <img src='{logo_urls["dark"]}' width='80%' class='logo-dark'>            
            """
        )
        project_dd = gr.Dropdown(
            label="Project", allow_custom_value=True, interactive=False
        )
        run_dd = gr.Dropdown(label="Run")

    navbar = gr.Navbar(
        value=[
            ("Metrics", ""),
            ("Media & Tables", "/media"),
            ("Files", "/files"),
            ("Runs", "/runs"),
        ],
        main_page_name=False,
    )

    run_details = gr.Markdown(RUN_DETAILS_TEMPLATE)

    run_config = gr.JSON(label="Run Config")

    def configure(request: gr.Request):
        project = request.query_params.get("selected_project")
        run = request.query_params.get("selected_run")
        runs = SQLiteStorage.get_runs(project)
        return project, gr.Dropdown(choices=runs, value=run)

    def update_run_details(project, run):
        config = SQLiteStorage.get_run_config(project, run)
        if not config:
            return gr.Markdown("No run details available"), {}

        group = config.get("_Group", "None")

        created = config.get("_Created", "Unknown")
        if created != "Unknown":
            created = utils.format_timestamp(created)

        username = config.get("_Username", "Unknown")
        if username and username != "None" and username != "Unknown":
            username = f"[{username}](https://huggingface.co/{username})"

        details_md = RUN_DETAILS_TEMPLATE.format(
            run_name=run, group=group, created=created, username=username
        )

        config_display = {k: v for k, v in config.items() if not k.startswith("_")}

        return gr.Markdown(details_md), config_display

    gr.on(
        [run_detail_page.load],
        fn=configure,
        outputs=[project_dd, run_dd],
        show_progress="hidden",
        queue=False,
        api_visibility="private",
    ).then(
        fns.update_navbar_value,
        inputs=[project_dd],
        outputs=[navbar],
        show_progress="hidden",
        api_visibility="private",
        queue=False,
    )

    gr.on(
        [run_dd.change],
        update_run_details,
        inputs=[project_dd, run_dd],
        outputs=[run_details, run_config],
        show_progress="hidden",
        api_visibility="private",
        queue=False,
    )
