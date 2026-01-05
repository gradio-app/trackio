import gradio as gr


class RunsTable(gr.HTML):
    def __init__(
        self,
        headers: list[str] | None = None,
        rows: list[list[str]] | None = None,
        *,
        value: list[int] | None = None,
        interactive: bool = True,
        **kwargs,
    ):
        headers = headers or []
        rows = rows or []
        value = value or []

        html_template = """
        <div class="runs-table-container">
            <div class="runs-table-scroll">
                <table class="runs-table">
                    <thead>
                        <tr>
                            <th class="checkbox-col">
                                <input type="checkbox" class="select-all-checkbox" ${!interactive ? 'disabled' : ''}>
                            </th>
                            ${headers.map((h, idx) => `<th class="${idx === 0 ? 'name-col' : ''}">${h}</th>`).join('')}
                        </tr>
                    </thead>
                    <tbody>
                        ${rows.length === 0 ? `
                            <tr class="empty-row">
                                <td colspan="${headers.length + 1}">No runs found</td>
                            </tr>
                        ` : rows.map((row, idx) => `
                            <tr data-idx="${idx}">
                                <td class="checkbox-col">
                                    <input type="checkbox" class="row-checkbox" data-idx="${idx}" ${(value || []).includes(idx) ? 'checked' : ''} ${!interactive ? 'disabled' : ''}>
                                </td>
                                ${row.map((cell, colIdx) => `<td class="col-${colIdx} ${colIdx === 0 ? 'name-col' : ''}">${cell}</td>`).join('')}
                            </tr>
                        `).join('')}
                    </tbody>
                </table>
            </div>
        </div>
        """

        css_template = """
        .runs-table-container {
            background: transparent;
            overflow: hidden;
        }
        .runs-table-scroll {
            overflow-x: auto;
            overflow-y: visible;
            width: 100%;
            max-width: 100%;
        }
        .runs-table {
            width: 100%;
            border-collapse: collapse;
            font-size: var(--text-md);
            min-width: max-content;
            border: none;
            background: transparent;
        }
        .runs-table thead {
            background: transparent;
            position: sticky;
            top: 0;
            z-index: 1;
        }
        .runs-table th {
            padding: 12px 16px;
            text-align: left;
            font-weight: 600;
            color: var(--block-title-text-color);
            white-space: nowrap;
            font-family: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, "Liberation Mono", monospace;
            border: 1px solid var(--border-color-primary);
        }
        .runs-table td {
            padding: 10px 16px;
            color: var(--body-text-color);
            border: 1px solid var(--border-color-primary);
        }
        .runs-table tbody tr.selected {
            background: var(--color-accent-soft);
        }
        .runs-table .checkbox-col {
            width: 40px;
            text-align: center;
            padding: 10px 12px;
            position: sticky;
            left: 0;
            background: var(--background-fill-primary);
            z-index: 2;
            border: 1px solid var(--border-color-primary);
        }
        .runs-table .checkbox-col::before {
            content: '';
            position: absolute;
            top: 0;
            bottom: 0;
            left: -1px;
            width: 1px;
            background: var(--border-color-primary);
            z-index: 100;
            pointer-events: none;
        }
        .runs-table .checkbox-col::after {
            content: '';
            position: absolute;
            top: 0;
            bottom: 0;
            right: -1px;
            width: 1px;
            background: var(--border-color-primary);
            z-index: 100;
            pointer-events: none;
        }
        .runs-table thead .checkbox-col {
            background: var(--background-fill-primary);
            z-index: 3;
        }
        .runs-table thead .checkbox-col::before,
        .runs-table thead .checkbox-col::after {
            z-index: 101;
        }
        .runs-table .name-col {
            position: sticky;
            left: 40px;
            background: var(--background-fill-primary);
            z-index: 2;
            border: 1px solid var(--border-color-primary);
        }
        .runs-table .name-col::before {
            content: '';
            position: absolute;
            top: 0;
            bottom: 0;
            left: -1px;
            width: 1px;
            background: var(--border-color-primary);
            z-index: 100;
            pointer-events: none;
        }
        .runs-table .name-col::after {
            content: '';
            position: absolute;
            top: 0;
            bottom: 0;
            right: -2px;
            width: 2px;
            background: var(--border-color-primary);
            z-index: 100;
            pointer-events: none;
        }
        .runs-table thead .name-col {
            background: var(--background-fill-primary);
            z-index: 3;
        }
        .runs-table thead .name-col::before,
        .runs-table thead .name-col::after {
            z-index: 101;
        }
        .runs-table tbody tr .checkbox-col,
        .runs-table tbody tr .name-col {
            background: var(--background-fill-primary);
        }
        .runs-table tbody tr.selected .checkbox-col,
        .runs-table tbody tr.selected .name-col {
            background: var(--color-accent-soft);
        }
        .runs-table input[type="checkbox"] {
            width: 16px;
            height: 16px;
            cursor: pointer;
            accent-color: var(--color-accent);
        }
        .runs-table input[type="checkbox"]:disabled {
            cursor: not-allowed;
            opacity: 0.5;
        }
        .runs-table a {
            color: var(--link-text-color);
            text-decoration: underline;
            text-decoration-style: dotted;
        }
        .runs-table a:hover {
            text-decoration-style: solid;
        }
        .runs-table .empty-row td {
            text-align: center;
            padding: 40px 16px;
            color: var(--block-label-text-color);
            font-style: italic;
        }
        .runs-table .col-0 {
            font-weight: 500;
        }
        """

        js_on_load = """
        function getRowCheckboxes() {
            return element.querySelectorAll('.row-checkbox');
        }

        function getSelectAllCheckbox() {
            return element.querySelector('.select-all-checkbox');
        }

        function updateSelectAllState() {
            const checkboxes = getRowCheckboxes();
            const selectAll = getSelectAllCheckbox();
            if (!selectAll || checkboxes.length === 0) return;

            const total = checkboxes.length;
            const checked = Array.from(checkboxes).filter(cb => cb.checked).length;

            if (checked === total) {
                selectAll.checked = true;
                selectAll.indeterminate = false;
            } else if (checked > 0) {
                selectAll.checked = false;
                selectAll.indeterminate = true;
            } else {
                selectAll.checked = false;
                selectAll.indeterminate = false;
            }
        }

        function updateRowStyles() {
            const checkboxes = getRowCheckboxes();
            checkboxes.forEach(cb => {
                const row = cb.closest('tr');
                if (cb.checked) {
                    row.classList.add('selected');
                } else {
                    row.classList.remove('selected');
                }
            });
        }

        function updateValue() {
            const checkboxes = getRowCheckboxes();
            props.value = Array.from(checkboxes)
                .filter(cb => cb.checked)
                .map(cb => parseInt(cb.dataset.idx, 10));
            updateSelectAllState();
            updateRowStyles();
            trigger('input');
        }

        element.addEventListener('change', (e) => {
            if (e.target.classList.contains('select-all-checkbox')) {
                const shouldCheck = e.target.checked;
                getRowCheckboxes().forEach(cb => { cb.checked = shouldCheck; });
                updateValue();
            } else if (e.target.classList.contains('row-checkbox')) {
                updateValue();
            }
        });

        updateSelectAllState();
        updateRowStyles();
        """

        super().__init__(
            value=value,
            html_template=html_template,
            css_template=css_template,
            js_on_load=js_on_load,
            headers=headers,
            rows=rows,
            interactive=interactive,
            **kwargs,
        )

    def api_info(self):
        return {
            "items": {"type": "integer"},
            "title": "Runs Table Selected Indices",
            "type": "array",
        }


if __name__ == "__main__":
    sample_headers = ["Name", "Group", "Username", "Created"]
    sample_rows = [
        [
            "<a href='/run?selected_project=test&selected_run=run-001'>run-001</a>",
            "experiment-a",
            "<a href='https://huggingface.co/johndoe'>johndoe</a>",
            "2024-01-15 10:30",
        ],
        [
            "<a href='/run?selected_project=test&selected_run=run-002'>run-002</a>",
            "experiment-a",
            "<a href='https://huggingface.co/janedoe'>janedoe</a>",
            "2024-01-15 11:45",
        ],
        [
            "<a href='/run?selected_project=test&selected_run=run-003'>run-003</a>",
            "experiment-b",
            "<a href='https://huggingface.co/johndoe'>johndoe</a>",
            "2024-01-16 09:00",
        ],
    ]

    with gr.Blocks() as demo:
        gr.Markdown("## Runs Table Demo")

        interactive_checkbox = gr.Checkbox(label="Interactive", value=True)

        table = RunsTable(
            headers=sample_headers,
            rows=sample_rows,
            value=[],
            interactive=True,
        )

        selected_output = gr.JSON(label="Selected Row Indices")

        table.input(lambda x: x, inputs=table, outputs=selected_output)

        def toggle_interactive(is_interactive):
            return RunsTable(
                headers=sample_headers,
                rows=sample_rows,
                value=[],
                interactive=is_interactive,
            )

        interactive_checkbox.change(
            toggle_interactive,
            inputs=[interactive_checkbox],
            outputs=[table],
        )

    demo.launch()
