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
        .accordion-header {
            display: ${hidden ? 'none' : 'flex'};
            align-items: center;
            cursor: pointer;
            user-select: none;
            margin-bottom: 8px;
        }

        .accordion-toggle {
            display: flex;
            align-items: center;
            gap: 8px;
            background: none;
            border: none;
            cursor: pointer;
            padding: 4px 0;
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
        let isOpen = props.open !== undefined ? props.open : true;

        function getContentNodes() {
            if (!header) {
                return Array.from(element.children).filter((child) => child.tagName !== 'STYLE');
            }
            const parent = header.parentElement;
            if (parent) {
                const siblingNodes = Array.from(parent.children).filter((node) => {
                    if (node === header) return false;
                    if (node.tagName === 'STYLE') return false;
                    if (node.contains(header)) return false;
                    return true;
                });
                if (siblingNodes.length > 0) {
                    return siblingNodes;
                }
            }
            return Array.from(element.children).filter((node) => {
                if (node === header) return false;
                if (node.tagName === 'STYLE') return false;
                if (node.contains(header)) return false;
                return true;
            });
        }

        function updateView() {
            if (arrow) {
                arrow.style.transform = isOpen ? 'rotate(90deg)' : 'rotate(0deg)';
            }
            for (const node of getContentNodes()) {
                node.style.display = isOpen ? '' : 'none';
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
