"""The Media and Tables page for the Trackio UI."""

import re
from dataclasses import dataclass

import gradio as gr
import pandas as pd

try:
    import trackio.utils as utils
    from trackio.media import TrackioAudio, TrackioImage, TrackioVideo
    from trackio.sqlite_storage import SQLiteStorage
    from trackio.table import Table
    from trackio.ui import fns
    from trackio.ui.components.colored_dropdown import ColoredDropdown
except ImportError:
    import utils
    from media import TrackioAudio, TrackioImage, TrackioVideo
    from sqlite_storage import SQLiteStorage
    from table import Table
    from ui import fns
    from ui.components.colored_dropdown import ColoredDropdown


def get_runs(project) -> list[str]:
    if not project:
        return []
    return SQLiteStorage.get_runs(project)


@dataclass
class MediaData:
    caption: str | None
    file_path: str
    type: str


def extract_media(logs: list[dict]) -> dict[str, list[MediaData]]:
    media_by_key: dict[str, list[MediaData]] = {}
    logs = sorted(logs, key=lambda x: x.get("step", 0))
    for log in logs:
        for key, value in log.items():
            if isinstance(value, dict):
                type = value.get("_type")
                if (
                    type == TrackioImage.TYPE
                    or type == TrackioVideo.TYPE
                    or type == TrackioAudio.TYPE
                ):
                    if key not in media_by_key:
                        media_by_key[key] = []
                    try:
                        media_data = MediaData(
                            file_path=utils.MEDIA_DIR / value.get("file_path"),
                            type=type,
                            caption=value.get("caption"),
                        )
                        media_by_key[key].append(media_data)
                    except Exception as e:
                        print(f"Media currently unavailable: {key}: {e}")
    return media_by_key


def filter_metrics_by_regex(metrics: list[str], filter_pattern: str) -> list[str]:
    """
    Filter metrics using regex pattern.

    Args:
        metrics: List of metric names to filter
        filter_pattern: Regex pattern to match against metric names

    Returns:
        List of metric names that match the pattern
    """
    if not filter_pattern.strip():
        return metrics

    try:
        pattern = re.compile(filter_pattern, re.IGNORECASE)
        return [metric for metric in metrics if pattern.search(metric)]
    except re.error:
        return [
            metric for metric in metrics if filter_pattern.lower() in metric.lower()
        ]


def refresh_runs_dropdown(project: str | None):
    if project is None:
        runs: list[str] = []
    else:
        runs = get_runs(project)

    color_palette = utils.get_color_palette()
    colors = [color_palette[i % len(color_palette)] for i in range(len(runs))]

    return ColoredDropdown(
        choices=runs,
        colors=colors,
        value=runs[0] if runs else None,
        placeholder=f"Select a run ({len(runs)})",
    )


with gr.Blocks() as media_page:
    with gr.Sidebar() as sidebar:
        logo_urls = utils.get_logo_urls()
        logo = gr.Markdown(
            f"""
                <img src='{logo_urls["light"]}' width='80%' class='logo-light'>
                <img src='{logo_urls["dark"]}' width='80%' class='logo-dark'>            
            """
        )
        project_dd = gr.Dropdown(label="Project", allow_custom_value=True)
        runs_dropdown = ColoredDropdown(choices=[], colors=[], label="Run")

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

    @gr.render(
        triggers=[
            media_page.load,
            runs_dropdown.change,
            project_dd.change,
        ],
        inputs=[project_dd, runs_dropdown],
        show_progress="hidden",
        queue=False,
    )
    def display_media_and_tables(project: str | None, selected_run: str | None):
        if not project or not selected_run:
            gr.Markdown("*Select a project and run to view media and tables*")
            return

        logs = SQLiteStorage.get_logs(project, selected_run)
        if not logs:
            gr.Markdown("*No data found for this run*")
            return

        df = pd.DataFrame(logs)

        media_by_key = extract_media(logs)

        has_media = media_by_key and any(media_by_key.values())
        has_tables = False

        table_cols = df.select_dtypes(include="object").columns
        table_cols = [c for c in table_cols if c not in utils.RESERVED_KEYS]
        table_cols = [
            c
            for c in table_cols
            if not (metric_df := df.dropna(subset=[c])).empty
            and isinstance(first_value := metric_df[c].iloc[0], dict)
            and first_value.get("_type") == Table.TYPE
        ]
        has_tables = len(table_cols) > 0

        if not has_media and not has_tables:
            gr.Markdown("*No media or tables found for this run*")
            return

        if has_media:
            for key, media_items in media_by_key.items():
                image_and_video = [
                    item
                    for item in media_items
                    if item.type in [TrackioImage.TYPE, TrackioVideo.TYPE]
                ]
                audio = [item for item in media_items if item.type == TrackioAudio.TYPE]
                if image_and_video:
                    gr.Gallery(
                        [(item.file_path, item.caption) for item in image_and_video],
                        label=key,
                        columns=6,
                        elem_classes=("media-gallery"),
                    )
                if audio:
                    with gr.Accordion(
                        label=key, elem_classes=("media-audio-accordion")
                    ):
                        for i in range(0, len(audio), 3):
                            with gr.Row(elem_classes=("media-audio-row")):
                                for item in audio[i : i + 3]:
                                    gr.Audio(
                                        value=item.file_path,
                                        label=item.caption,
                                        elem_classes=("media-audio-item"),
                                    )

        if has_tables:
            with gr.Accordion(f"Tables ({len(table_cols)})", open=True):
                with gr.Row(key="row"):
                    for metric_idx, metric_name in enumerate(table_cols):
                        metric_df = df.dropna(subset=[metric_name])
                        if not metric_df.empty:
                            value = metric_df[metric_name]
                            first_value = value.iloc[0]
                            if (
                                isinstance(first_value, dict)
                                and "_type" in first_value
                                and first_value["_type"] == Table.TYPE
                            ):
                                try:
                                    with gr.Column():
                                        s = gr.Slider(
                                            value=len(value),
                                            minimum=1,
                                            maximum=len(value),
                                            step=1,
                                            container=False,
                                            visible=len(value) > 1,
                                            interactive=True,
                                        )
                                        processed_data = Table.to_display_format(
                                            value.iloc[-1]["_value"]
                                        )
                                        df_table = pd.DataFrame(processed_data)
                                        table = gr.DataFrame(
                                            df_table,
                                            label=f"{metric_name} (index {len(value)})",
                                            key=f"table-{metric_idx}",
                                            wrap=True,
                                            datatype="markdown",
                                            preserved_by_key=None,
                                        )

                                        def get_table_at_index(index: int):
                                            value = metric_df[metric_name]
                                            processed_data = Table.to_display_format(
                                                value.iloc[index - 1]["_value"]
                                            )
                                            df_ = pd.DataFrame(processed_data)
                                            return gr.DataFrame(
                                                df_,
                                                label=f"{metric_name} (index {index})",
                                            )

                                        s.input(
                                            get_table_at_index,
                                            inputs=s,
                                            outputs=table,
                                            show_progress="hidden",
                                        )
                                except Exception as e:
                                    gr.Warning(
                                        f"Column {metric_name} failed to render as a table: {e}"
                                    )

    gr.on(
        [timer.tick],
        fn=lambda: gr.Dropdown(info=fns.get_project_info()),
        outputs=[project_dd],
        show_progress="hidden",
        api_visibility="private",
    )

    gr.on(
        [media_page.load],
        fn=fns.get_projects,
        outputs=project_dd,
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
        [project_dd.change],
        fn=refresh_runs_dropdown,
        inputs=[project_dd],
        outputs=[runs_dropdown],
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
