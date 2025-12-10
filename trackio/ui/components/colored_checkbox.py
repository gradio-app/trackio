import gradio as gr


class ColoredCheckboxGroup(gr.HTML):
    def __init__(
        self,
        choices: list[str] | None = None,
        *,
        value: list[str] | None = None,
        colors: list[str] | None = None,
        label: str | None = None,
        **kwargs,
    ):
        html_template = """
        <div class="colored-checkbox-container">
            <div class="header-row">
                <label class="checkbox-label select-all-label">
                    <input type="checkbox" class="select-all-input">
                </label>
                ${label ? `<span class="container-label">${label}</span>` : ''}
            </div>
            <div class="colored-checkbox-group">
                ${choices.map((choice, i) => `
                    <label class="checkbox-label item-checkbox">
                        <input type="checkbox" value="${choice}" ${(value || []).includes(choice) ? 'checked' : ''}>
                        <span class="color-dot" style="background: ${colors[i]};"></span>
                        ${choice}
                    </label>
                `).join('')}
            </div>
        </div>
        """

        css_template = """
        .colored-checkbox-container {
            border: 1px solid var(--border-color-primary);
            border-radius: var(--radius-lg);
            padding: var(--spacing-lg);
            background-color: var(--block-background-fill);
        }
        .header-row {
            display: flex;
            align-items: center;
            margin-bottom: var(--spacing-md);
        }
        .container-label {
            color: var(--block-title-text-color);
        }
        .colored-checkbox-group {
            display: flex;
            flex-direction: column;
            gap: 6px;
            max-height: 280px;
            overflow-y: auto;
        }
        .checkbox-label { display: flex; align-items: center; cursor: pointer; }
        .checkbox-label input { margin-right: 8px; }
        .color-dot {
            width: 10px;
            height: 10px;
            border-radius: 50%;
            margin-right: 6px;
            flex-shrink: 0;
        }
        """

        js_on_load = """
        function getCheckboxes() {
            return element.querySelectorAll('.item-checkbox input[type="checkbox"]');
        }
        
        function getSelectAllInput() {
            return element.querySelector('.select-all-input');
        }
        
        function updateSelectAllState() {
            const checkboxes = getCheckboxes();
            const selectAllInput = getSelectAllInput();
            if (!selectAllInput) return;
            const total = checkboxes.length;
            const checked = Array.from(checkboxes).filter(cb => cb.checked).length;
            if (checked === total && total > 0) {
                selectAllInput.checked = true;
                selectAllInput.indeterminate = false;
            } else if (checked > 0) {
                selectAllInput.checked = false;
                selectAllInput.indeterminate = true;
            } else {
                selectAllInput.checked = false;
                selectAllInput.indeterminate = false;
            }
        }
        
        function updateValue() {
            const checkboxes = getCheckboxes();
            props.value = Array.from(checkboxes)
                .filter(cb => cb.checked)
                .map(cb => cb.value);
            updateSelectAllState();
            trigger('input');
        }
        
        element.addEventListener('change', (e) => {
            if (e.target.classList.contains('select-all-input')) {
                const shouldCheck = e.target.checked;
                getCheckboxes().forEach(cb => { cb.checked = shouldCheck; });
                updateValue();
            } else if (e.target.closest('.item-checkbox')) {
                updateValue();
            }
        });
        
        const observer = new MutationObserver(() => {
            updateSelectAllState();
        });
        observer.observe(element, { childList: true, subtree: true, attributes: true });
        
        updateSelectAllState();
        """

        super().__init__(
            value=value or [],
            html_template=html_template,
            css_template=css_template,
            js_on_load=js_on_load,
            choices=choices,
            colors=colors,
            label=label,
            **kwargs,
        )

    def api_info(self):
        return {
            "items": {"enum": self.props["choices"], "type": "string"},
            "title": "Checkbox Group",
            "type": "array",
        }


if __name__ == "__main__":

    def generate_color_variants(color: str, count: int):
        if color.startswith("rgb"):
            rgb_values = (
                color.replace("rgba", "").replace("rgb", "").strip("()").split(",")
            )
            r, g, b = (
                int(float(rgb_values[0])),
                int(float(rgb_values[1])),
                int(float(rgb_values[2])),
            )
        else:
            r = int(color[1:3], 16)
            g = int(color[3:5], 16)
            b = int(color[5:7], 16)

        colors = []
        for i in range(count):
            factor = 0.3 + (0.7 * i / max(count - 1, 1))
            nr = int(r * factor + (255 - r * factor) * (1 - factor) * 0.3)
            ng = int(g * factor + (255 - g * factor) * (1 - factor) * 0.3)
            nb = int(b * factor + (255 - b * factor) * (1 - factor) * 0.3)
            nr, ng, nb = min(255, nr), min(255, ng), min(255, nb)
            colors.append(f"#{nr:02x}{ng:02x}{nb:02x}")
        return colors

    def update_colors(color: str, s: int):
        items = [f"Item {i + 1} ({s + 1})" for i in range(12)]
        colors = generate_color_variants(color, len(items))
        return ColoredCheckboxGroup(
            choices=items,
            colors=colors,
            label=f"Runs ({s + 1})",
        ), s + 1

    with gr.Blocks() as demo:
        s = gr.State(0)
        with gr.Row():
            with gr.Column():
                cp = gr.ColorPicker(value="#FF0000")
            with gr.Column(scale=2):
                items = [f"Item {i + 1}" for i in range(15)]
                colors = generate_color_variants("#FF0000", len(items))
                cg = ColoredCheckboxGroup(
                    choices=items,
                    colors=colors,
                    label="Runs",
                )
                gr.Interface(
                    fn=lambda x: " ".join(x),
                    inputs=cg,
                    outputs=gr.Textbox(label="output"),
                )
        cp.change(
            update_colors, inputs=[cp, s], outputs=[cg, s], show_progress="hidden"
        )
    demo.launch()
