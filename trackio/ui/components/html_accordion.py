import gradio as gr


class HTMLAccordion(gr.HTML):
    def __init__(
        self,
        label: str = "",
        *,
        open: bool = True,
        hidden: bool = False,
        **kwargs,
    ):
        html_template = """
        <div class="accordion-header">
            <button class="accordion-toggle" type="button">
                <span class="accordion-arrow">&#9654;</span>
                <span class="accordion-label">${label}</span>
            </button>
        </div>
        @children
        """

        css_template = """
        border: ${hidden ? 'none' : '1px solid var(--border-color-primary, #e5e7eb)'};
        border-radius: 8px;
        overflow: hidden;

        .accordion-header {
            display: ${hidden ? 'none' : 'flex'};
            align-items: center;
            cursor: pointer;
            user-select: none;
            background: var(--background-fill-secondary, transparent);
        }

        .accordion-toggle {
            display: flex;
            align-items: center;
            gap: 8px;
            background: none;
            border: none;
            cursor: pointer;
            padding: 10px 12px;
            width: 100%;
            text-align: left;
            color: var(--body-text-color);
            font-size: var(--text-md);
            font-weight: 600;
        }

        .accordion-toggle:hover {
            opacity: 0.8;
        }

        .accordion-arrow {
            font-size: 0.65em;
            transition: transform 0.2s ease;
            display: inline-block;
        }
        """

        js_on_load = """
        const header = element.querySelector('.accordion-header');
        const arrow = element.querySelector('.accordion-arrow');
        const headerParent = header ? header.parentElement : null;
        let isOpen = props.open !== undefined ? props.open : true;

        function getContentNodes() {
            return Array.from(element.children).filter((node) => {
                if (node === headerParent) return false;
                if (node.tagName === 'STYLE') return false;
                return true;
            });
        }

        function updateView() {
            if (arrow) {
                arrow.style.transform = isOpen ? 'rotate(90deg)' : 'rotate(0deg)';
            }
            if (header) {
                header.style.borderBottom = isOpen
                    ? '1px solid var(--border-color-primary, #e5e7eb)'
                    : 'none';
            }
            for (const node of getContentNodes()) {
                node.style.display = isOpen ? '' : 'none';
                node.style.padding = '0 6px';
            }
        }

        updateView();

        if (header) {
            header.addEventListener('click', () => {
                isOpen = !isOpen;
                props.open = isOpen;
                updateView();
            });
        }
        """

        super().__init__(
            html_template=html_template,
            css_template=css_template,
            js_on_load=js_on_load,
            label=label,
            open=open,
            hidden=hidden,
            apply_default_css=False,
            **kwargs,
        )
