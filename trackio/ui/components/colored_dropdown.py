import gradio as gr


class ColoredDropdown(gr.HTML):
    def __init__(
        self,
        choices: list[str] | None = None,
        *,
        placeholder: str = "Select...",
        value: str | None = None,
        colors: list[str] | None = None,
        label: str | None = None,
        **kwargs,
    ):
        html_template = """
        <div class="colored-dropdown-container">
            ${label ? `<span class="dropdown-label">${label}</span>` : ''}
            <div class="dropdown-wrapper">
                <button type="button" class="dropdown-trigger">
                    <span class="selected-display">
                        ${value ? `<span class="color-dot" style="background: ${colors[choices.indexOf(value)]};"></span>${value}` : `<span class="placeholder">${placeholder}</span>`}
                    </span>
                    <svg class="dropdown-arrow" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <polyline points="6 9 12 15 18 9"></polyline>
                    </svg>
                </button>
                <div class="dropdown-menu">
                    ${choices.map((choice, i) => `
                        <div class="dropdown-item ${value === choice ? 'selected' : ''}" data-value="${choice}" data-color="${colors[i]}">
                            <span class="color-dot" style="background: ${colors[i]};"></span>
                            <span class="item-text">${choice}</span>
                        </div>
                    `).join('')}
                </div>
            </div>
        </div>
        """

        css_template = """
        .colored-dropdown-container {
            display: flex;
            flex-direction: column;
            gap: var(--spacing-sm);
            overflow: visible;
        }
        .dropdown-label {
            color: var(--block-title-text-color);
            font-size: var(--text-sm);
            font-weight: 500;
        }
        .dropdown-wrapper {
            position: relative;
            z-index: 1;
        }
        .dropdown-trigger {
            width: 100%;
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 8px 12px;
            border: 1px solid var(--border-color-primary);
            border-radius: var(--radius-md);
            background: var(--input-background-fill);
            color: var(--body-text-color);
            cursor: pointer;
            font-size: var(--text-md);
            text-align: left;
            transition: border-color 0.15s ease;
        }
        .dropdown-trigger:hover {
            border-color: var(--border-color-accent);
        }
        .dropdown-trigger:focus {
            outline: none;
            border-color: var(--color-accent);
            box-shadow: 0 0 0 2px var(--color-accent-soft);
        }
        .selected-display {
            display: flex;
            align-items: center;
            gap: 8px;
            flex: 1;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }
        .placeholder {
            color: var(--input-placeholder-color);
        }
        .dropdown-arrow {
            width: 16px;
            height: 16px;
            flex-shrink: 0;
            transition: transform 0.2s ease;
        }
        .dropdown-wrapper.open .dropdown-arrow {
            transform: rotate(180deg);
        }
        .dropdown-menu {
            position: fixed;
            max-height: 240px;
            overflow-y: auto;
            background: var(--background-fill-primary);
            border: 1px solid var(--border-color-primary);
            border-radius: var(--radius-md);
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
            z-index: 9999;
            display: none;
        }
        .dropdown-wrapper.open .dropdown-menu {
            display: block;
        }
        .dropdown-item {
            display: flex;
            align-items: center;
            gap: 8px;
            padding: 8px 12px;
            cursor: pointer;
            transition: background 0.1s ease;
        }
        .dropdown-item:hover {
            background: var(--background-fill-secondary);
        }
        .dropdown-item.selected {
            background: var(--color-accent-soft);
        }
        .item-text {
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }
        .color-dot {
            width: 10px;
            height: 10px;
            border-radius: 50%;
            flex-shrink: 0;
        }
        """

        js_on_load = """
        const wrapper = element.querySelector('.dropdown-wrapper');
        const triggerButton = element.querySelector('.dropdown-trigger');
        const menu = element.querySelector('.dropdown-menu');
        const selectedDisplay = element.querySelector('.selected-display');
        
        function positionMenu() {
            const rect = triggerButton.getBoundingClientRect();
            menu.style.position = 'fixed';
            menu.style.top = (rect.bottom + 4) + 'px';
            menu.style.left = rect.left + 'px';
            menu.style.width = rect.width + 'px';
            menu.style.right = 'auto';
        }
        
        triggerButton.addEventListener('click', (e) => {
            e.stopPropagation();
            wrapper.classList.toggle('open');
            if (wrapper.classList.contains('open')) {
                positionMenu();
            }
        });
        
        menu.addEventListener('click', (e) => {
            const item = e.target.closest('.dropdown-item');
            if (!item) return;
            
            const value = item.dataset.value;
            const color = item.dataset.color;
            
            menu.querySelectorAll('.dropdown-item').forEach(el => el.classList.remove('selected'));
            item.classList.add('selected');
            
            selectedDisplay.innerHTML = `<span class="color-dot" style="background: ${color};"></span>${value}`;
            
            props.value = value;
            trigger('input');
            
            wrapper.classList.remove('open');
        });
        
        document.addEventListener('click', (e) => {
            if (!element.contains(e.target)) {
                wrapper.classList.remove('open');
            }
        });
        
        window.addEventListener('resize', () => {
            if (wrapper.classList.contains('open')) {
                positionMenu();
            }
        });
        
        window.addEventListener('scroll', () => {
            if (wrapper.classList.contains('open')) {
                positionMenu();
            }
        }, true);
        
        triggerButton.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                wrapper.classList.toggle('open');
                if (wrapper.classList.contains('open')) {
                    positionMenu();
                }
            } else if (e.key === 'Escape') {
                wrapper.classList.remove('open');
            }
        });
        """

        super().__init__(
            value=value,
            html_template=html_template,
            css_template=css_template,
            js_on_load=js_on_load,
            choices=choices,
            colors=colors,
            label=label,
            placeholder=placeholder,
            **kwargs,
        )

    def api_info(self):
        return {
            "enum": self.props["choices"],
            "title": "Dropdown",
            "type": "string",
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

    def update_dropdown(color: str, s: int):
        items = [f"Item {i + 1} ({s + 1})" for i in range(12)]
        colors = generate_color_variants(color, len(items))
        return ColoredDropdown(
            choices=items,
            colors=colors,
            label=f"Select Item ({s + 1})",
        ), s + 1

    with gr.Blocks() as demo:
        s = gr.State(0)
        with gr.Row():
            with gr.Column():
                cp = gr.ColorPicker(value="#FF0000", label="Base Color")
            with gr.Column(scale=2):
                items = [f"Item {i + 1}" for i in range(15)]
                colors = generate_color_variants("#FF0000", len(items))
                dropdown = ColoredDropdown(
                    choices=items,
                    colors=colors,
                    label="Select Item",
                    value=items[0],
                )
                output = gr.Textbox(label="Selected Value")
                dropdown.input(lambda x: x, inputs=dropdown, outputs=output)
        cp.change(
            update_dropdown,
            inputs=[cp, s],
            outputs=[dropdown, s],
            show_progress="hidden",
        )
    demo.launch()
