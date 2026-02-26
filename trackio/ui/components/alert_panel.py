import gradio as gr

HTML_TEMPLATE = """\
<div class="alert-header">
    <span class="alert-count">Alerts</span>
    <span class="alert-badge-count">${value.length}</span>
    <span class="alert-chevron">▾</span>
</div>
<div class="alert-body">
    <div class="alert-filters">
        <button class="filter-pill filter-active" data-level="info">🔵 Info</button>
        <button class="filter-pill filter-active" data-level="warn">🟡 Warn</button>
        <button class="filter-pill filter-active" data-level="error">🔴 Error</button>
    </div>
    {{#each value}}
    <div class="alert-item alert-{{this.level}}" data-level="{{this.level}}">
        <div class="alert-item-top">
            <span class="alert-badge">{{this.badge}}</span>
            <span class="alert-title">{{this.title}}</span>
        </div>
        <div class="alert-item-meta">{{this.meta}}</div>
        {{#if this.text}}<div class="alert-item-text">{{this.text}}</div>{{/if}}
    </div>
    {{/each}}
</div>
"""

CSS_TEMPLATE = """\
position: fixed;
bottom: 24px;
right: 24px;
width: 33%;
min-width: 320px;
max-width: 480px;
z-index: 9999;
border-radius: 12px;
box-shadow: 0 4px 24px rgba(0, 0, 0, 0.12);
background: var(--background-fill-primary, #fff);
border: 1px solid var(--border-color-primary, #e5e7eb);
font-family: var(--font, system-ui, sans-serif);
font-size: 14px;
color: var(--body-text-color, #374151);
overflow: hidden;
display: none;

.alert-header {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 10px 16px;
    cursor: pointer;
    user-select: none;
    background: var(--background-fill-secondary, #f9fafb);
}
.alert-count { flex: 1; font-weight: 600; font-size: 13px; }
.alert-badge-count {
    background: var(--body-text-color-subdued, #6b7280);
    color: #fff;
    font-size: 11px;
    font-weight: 700;
    min-width: 20px;
    height: 20px;
    line-height: 20px;
    text-align: center;
    border-radius: 10px;
    padding: 0 6px;
}
.alert-chevron {
    font-size: 12px;
    color: var(--body-text-color-subdued, #6b7280);
    transition: transform 0.2s;
}

.alert-body {
    max-height: 0;
    overflow: hidden;
}

.alert-filters {
    display: flex;
    gap: 6px;
    padding: 8px 16px;
    border-bottom: 1px solid var(--border-color-primary, #e5e7eb);
    background: var(--background-fill-primary, #fff);
    position: sticky;
    top: 0;
    z-index: 1;
}
.filter-pill {
    font-size: 11px;
    padding: 3px 10px;
    border-radius: 12px;
    border: 1px solid var(--border-color-primary, #e5e7eb);
    background: var(--background-fill-primary, #fff);
    color: var(--body-text-color-subdued, #6b7280);
    cursor: pointer;
    opacity: 0.45;
    transition: opacity 0.15s;
}
.filter-pill.filter-active {
    opacity: 1;
    font-weight: 600;
    color: var(--body-text-color, #374151);
}

.alert-item {
    padding: 10px 16px;
    border-bottom: 1px solid var(--border-color-primary, #e5e7eb);
    border-left: 3px solid transparent;
}
.alert-item:last-child { border-bottom: none; }
.alert-item.hidden { display: none; }
.alert-info { border-left-color: #3b82f6; }
.alert-warn { border-left-color: #f59e0b; }
.alert-error { border-left-color: #ef4444; }

.alert-item-top {
    display: flex;
    align-items: center;
    gap: 6px;
}
.alert-badge { font-size: 10px; }
.alert-title { font-weight: 600; font-size: 13px; }

.alert-item-meta {
    font-size: 11px;
    color: var(--body-text-color-subdued, #6b7280);
    margin-top: 2px;
}

.alert-item-text {
    margin-top: 4px;
    font-size: 12px;
    color: var(--body-text-color-subdued, #6b7280);
    line-height: 1.4;
}

@keyframes alert-header-flash {
    0%, 100% { background: var(--background-fill-secondary, #f9fafb); }
    50% { background: #fef3c7; }
}
.alert-header.flash {
    animation: alert-header-flash 0.5s ease-in-out 3;
}
"""

JS_ON_LOAD = """\
const _stored = sessionStorage.getItem('trackio_alert_expanded');
let isExpanded = _stored === null ? true : _stored === 'true';
let alertCount = 0;
const activeFilters = new Set(['info', 'warn', 'error']);

function applyFilters() {
    element.querySelectorAll('.alert-item').forEach(item => {
        const level = item.getAttribute('data-level');
        item.classList.toggle('hidden', !activeFilters.has(level));
    });
}

function restoreState(animate) {
    const body = element.querySelector('.alert-body');
    const chevron = element.querySelector('.alert-chevron');
    if (!body || !chevron) return;
    if (!animate) {
        body.style.transition = 'none';
        void body.offsetHeight;
    } else {
        body.style.transition = 'max-height 0.3s ease';
    }
    body.style.maxHeight = isExpanded ? '50vh' : '0';
    body.style.overflow = isExpanded ? 'auto' : 'hidden';
    chevron.style.transform = isExpanded ? 'rotate(180deg)' : '';
    if (!animate) {
        void body.offsetHeight;
        body.style.transition = 'max-height 0.3s ease';
    }
    applyFilters();
}

element.addEventListener('click', (e) => {
    const pill = e.target.closest('.filter-pill');
    if (pill) {
        const level = pill.getAttribute('data-level');
        if (activeFilters.has(level)) {
            activeFilters.delete(level);
            pill.classList.remove('filter-active');
        } else {
            activeFilters.add(level);
            pill.classList.add('filter-active');
        }
        applyFilters();
        return;
    }
    if (e.target.closest('.alert-header')) {
        isExpanded = !isExpanded;
        sessionStorage.setItem('trackio_alert_expanded', isExpanded);
        restoreState(true);
        if (isExpanded) {
            setTimeout(() => {
                const body = element.querySelector('.alert-body');
                if (body) body.scrollTop = body.scrollHeight;
            }, 320);
        }
    }
});

const observer = new MutationObserver(() => {
    requestAnimationFrame(() => {
        const items = element.querySelectorAll('.alert-item');
        const newCount = items.length;
        element.style.display = newCount === 0 ? 'none' : 'block';
        restoreState(false);
        const pills = element.querySelectorAll('.filter-pill');
        pills.forEach(p => {
            p.classList.toggle('filter-active',
                activeFilters.has(p.getAttribute('data-level')));
        });
        if (newCount > alertCount && alertCount > 0) {
            const header = element.querySelector('.alert-header');
            if (header) {
                header.classList.remove('flash');
                void header.offsetWidth;
                header.classList.add('flash');
            }
            if (isExpanded) {
                const body = element.querySelector('.alert-body');
                if (body) body.scrollTop = body.scrollHeight;
            }
        }
        alertCount = newCount;
    });
});
observer.observe(element, { childList: true, subtree: true });
"""


class AlertPanel(gr.HTML):
    def __init__(self, **kwargs):
        super().__init__(
            value=[],
            html_template=HTML_TEMPLATE,
            css_template=CSS_TEMPLATE,
            js_on_load=JS_ON_LOAD,
            **kwargs,
        )
