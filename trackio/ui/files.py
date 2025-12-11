"""The Files page for the Trackio UI."""

import os
from pathlib import Path

import gradio as gr

try:
    import trackio.utils as utils
    from trackio.ui import fns
except ImportError:
    import utils
    from ui import fns


def get_files_path(project: str | None) -> str | None:
    """Get the files directory path for a project. If the directory does not exist, returns None."""
    if not project:
        return None
    files_dir = utils.MEDIA_DIR / project / "files"
    if not files_dir.exists():
        return None
    return str(files_dir)


def update_file_explorer(project: str | None):
    """Update the file explorer based on the selected project."""
    files_path = get_files_path(project)
    if files_path:
        return gr.FileExplorer(root_dir=files_path, visible=True)
    else:
        return gr.FileExplorer(visible=False)


def extract_files(project: str, files_or_diectories: list[str | Path]):
    """Extract files from a list of files or directories."""
    files = []
    root_dir = Path(get_files_path(project))
    for file_or_directory in files_or_diectories:
        if os.path.isfile(file_or_directory):
            files.append(str(root_dir / file_or_directory))
    return files


with gr.Blocks() as files_page:
    with gr.Sidebar() as sidebar:
        logo_urls = utils.get_logo_urls()
        logo = gr.Markdown(
            f"""
                <img src='{logo_urls["light"]}' width='80%' class='logo-light'>
                <img src='{logo_urls["dark"]}' width='80%' class='logo-dark'>            
            """
        )
        project_dd = gr.Dropdown(label="Project", allow_custom_value=True)

    navbar = gr.Navbar(
        value=[
            ("Metrics", ""),
            ("Media & Tables", "/media"),
            ("Runs", "/runs"),
            ("Files", "/files"),
        ],
        main_page_name=False,
    )
    timer = gr.Timer(value=1)

    gr.Markdown("## Files")
    file_explorer = gr.FileExplorer(label="Uploaded Files", visible=False)
    file_downloader = gr.Files(label="Download Selected Files")

    gr.on(
        [timer.tick],
        fn=lambda: gr.Dropdown(info=fns.get_project_info()),
        outputs=[project_dd],
        show_progress="hidden",
        api_visibility="private",
    )

    gr.on(
        [files_page.load],
        fn=fns.get_projects,
        outputs=project_dd,
        show_progress="hidden",
        queue=False,
        api_visibility="private",
    ).then(
        fn=update_file_explorer,
        inputs=[project_dd],
        outputs=[file_explorer],
        show_progress="hidden",
        api_visibility="private",
        queue=False,
    ).then(
        fns.update_navbar_value,
        inputs=[project_dd],
        outputs=[navbar],
        show_progress="hidden",
        api_visibility="private",
        queue=False,
    )

    gr.on(
        [project_dd.change],
        fn=update_file_explorer,
        inputs=[project_dd],
        outputs=[file_explorer],
        show_progress="hidden",
        api_visibility="private",
        queue=False,
    ).then(
        fns.update_navbar_value,
        inputs=[project_dd],
        outputs=[navbar],
        show_progress="hidden",
        api_visibility="private",
        queue=False,
    )

    gr.on(
        [file_explorer.change],
        fn=extract_files,
        inputs=[project_dd, file_explorer],
        outputs=[file_downloader],
    )
