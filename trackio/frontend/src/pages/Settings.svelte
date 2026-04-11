<script>
  import {
    getThemePreference,
    setThemePreference,
  } from "../lib/theme.js";

  let { spaceId = null, selectedProject = null } = $props();

  let themeChoice = $state(getThemePreference());
  let copiedIdx = $state(null);

  const pythonSnippet = `import trackio

trackio.init(project="my-project", run="run-1")
for step in range(100):
    trackio.log({"loss": compute_loss(), "lr": scheduler.get_lr()})
trackio.finish()`;

  function switchTheme(value) {
    themeChoice = value;
    setThemePreference(value);
  }

  function spaceFlag() {
    return spaceId ? ` --space ${spaceId}` : "";
  }

  let commands = $derived.by(() => {
    const sf = spaceFlag();
    const proj = selectedProject || "<project>";
    return [
      {
        title: "Launch Dashboard",
        description: "Open the Trackio dashboard UI",
        cmd: `trackio show`,
      },
      {
        title: "Launch Dashboard (specific project)",
        description: "Open the dashboard filtered to a single project",
        cmd: `trackio show --project "${proj}"`,
      },
      {
        title: "List Projects",
        description: "Show all tracked projects",
        cmd: `trackio${sf} list projects`,
      },
      {
        title: "List Runs",
        description: "Show all runs in a project",
        cmd: `trackio${sf} list runs --project "${proj}"`,
      },
      {
        title: "List Metrics",
        description: "Show metrics logged for a specific run",
        cmd: `trackio${sf} list metrics --project "${proj}" --run <run>`,
      },
      {
        title: "Project Summary",
        description: "Get a summary of a project",
        cmd: `trackio${sf} summary --project "${proj}"`,
      },
      {
        title: "Run Summary",
        description: "Get details about a specific run",
        cmd: `trackio${sf} summary --project "${proj}" --run <run>`,
      },
      {
        title: "Sync to HF Space",
        description: "Sync a local project to a Hugging Face Space",
        cmd: `trackio sync --project "${proj}"`,
      },
      {
        title: "Check Status",
        description: "Show sync status for all local projects",
        cmd: `trackio status`,
      },
    ];
  });

  async function copyCommand(cmd, idx) {
    try {
      await navigator.clipboard.writeText(cmd);
      copiedIdx = idx;
      setTimeout(() => {
        if (copiedIdx === idx) copiedIdx = null;
      }, 1500);
    } catch {
      // fallback
    }
  }
</script>

<div class="settings-page">
  <div class="settings-content">
    <h2 class="page-title">Settings</h2>

    <section class="settings-section">
      <h3 class="section-title">Appearance</h3>
      <p class="section-desc">Choose how the dashboard looks to you. Select a theme or sync with your system preference.</p>
      <div class="theme-switcher">
        {#each [
          { value: "system", label: "System", icon: "💻" },
          { value: "light", label: "Light", icon: "☀️" },
          { value: "dark", label: "Dark", icon: "🌙" },
        ] as opt}
          <button
            class="theme-option"
            class:selected={themeChoice === opt.value}
            onclick={() => switchTheme(opt.value)}
          >
            <span class="theme-icon">{opt.icon}</span>
            <span class="theme-label">{opt.label}</span>
          </button>
        {/each}
      </div>
    </section>

    <section class="settings-section">
      <h3 class="section-title">CLI Commands</h3>
      <p class="section-desc">
        Common Trackio CLI commands for interacting with your data.
        {#if spaceId}
          Running on Space <strong>{spaceId}</strong> — commands auto-include <code>--space</code>.
        {/if}
      </p>

      {#if spaceId}
        <div class="space-badge">
          <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
            <circle cx="8" cy="8" r="6.5" />
            <path d="M8 5v3l2 1" />
          </svg>
          Connected to Space: {spaceId}
        </div>
      {/if}

      <div class="commands-list">
        {#each commands as cmd, i}
          <div class="command-card">
            <div class="command-header">
              <span class="command-title">{cmd.title}</span>
              <span class="command-desc">{cmd.description}</span>
            </div>
            <div class="command-body">
              <code class="command-code">{cmd.cmd}</code>
              <button
                class="copy-btn"
                onclick={() => copyCommand(cmd.cmd, i)}
                title="Copy command"
              >
                {#if copiedIdx === i}
                  <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M3.5 8.5l3 3 6-7" />
                  </svg>
                {:else}
                  <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
                    <rect x="5" y="5" width="8" height="8" rx="1.5" />
                    <path d="M11 5V3.5A1.5 1.5 0 009.5 2h-6A1.5 1.5 0 002 3.5v6A1.5 1.5 0 003.5 11H5" />
                  </svg>
                {/if}
              </button>
            </div>
          </div>
        {/each}
      </div>
    </section>

    <section class="settings-section">
      <h3 class="section-title">Python Quick Start</h3>
      <p class="section-desc">Log metrics from your training script with just a few lines.</p>
      <div class="command-card">
        <div class="command-body code-block">
          <pre class="command-code"><code>{pythonSnippet}</code></pre>
          <button
            class="copy-btn code-copy-btn"
            onclick={() => copyCommand(pythonSnippet, -1)}
            title="Copy code"
          >
            {#if copiedIdx === -1}
              <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M3.5 8.5l3 3 6-7" />
              </svg>
            {:else}
              <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
                <rect x="5" y="5" width="8" height="8" rx="1.5" />
                <path d="M11 5V3.5A1.5 1.5 0 009.5 2h-6A1.5 1.5 0 002 3.5v6A1.5 1.5 0 003.5 11H5" />
              </svg>
            {/if}
          </button>
        </div>
      </div>
    </section>
  </div>
</div>

<style>
  .settings-page {
    padding: 20px 24px;
    overflow-y: auto;
    flex: 1;
  }
  .settings-content {
    max-width: 720px;
  }
  .page-title {
    color: var(--body-text-color, #1f2937);
    font-size: 18px;
    font-weight: 700;
    margin: 0 0 20px;
  }
  .settings-section {
    margin-bottom: 32px;
  }
  .section-title {
    color: var(--body-text-color, #1f2937);
    font-size: 15px;
    font-weight: 600;
    margin: 0 0 4px;
  }
  .section-desc {
    color: var(--body-text-color-subdued, #6b7280);
    font-size: var(--text-sm, 12px);
    margin: 0 0 12px;
    line-height: 1.5;
  }
  .section-desc code {
    background: var(--background-fill-secondary, #f3f4f6);
    padding: 1px 5px;
    border-radius: var(--radius-sm, 3px);
    font-size: 11px;
  }
  .section-desc strong {
    color: var(--color-accent, #f97316);
  }

  .theme-switcher {
    display: flex;
    gap: 8px;
  }
  .theme-option {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 10px 20px;
    border: 1px solid var(--border-color-primary, #e5e7eb);
    border-radius: var(--radius-lg, 8px);
    background: var(--background-fill-primary, white);
    color: var(--body-text-color-subdued, #6b7280);
    font-size: var(--text-md, 14px);
    cursor: pointer;
    transition: all 0.15s;
  }
  .theme-option:hover {
    border-color: var(--body-text-color-subdued, #9ca3af);
    color: var(--body-text-color, #1f2937);
  }
  .theme-option.selected {
    border-color: var(--color-accent, #f97316);
    background: var(--color-accent-soft, #fff7ed);
    color: var(--body-text-color, #1f2937);
    font-weight: 500;
  }
  .theme-icon {
    font-size: 16px;
  }

  .space-badge {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 6px 12px;
    margin-bottom: 12px;
    border-radius: var(--radius-lg, 8px);
    background: var(--color-accent-soft, #fff7ed);
    color: var(--color-accent, #f97316);
    font-size: var(--text-sm, 12px);
    font-weight: 500;
    border: 1px solid var(--color-accent, #f97316);
  }

  .commands-list {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  .command-card {
    border: 1px solid var(--border-color-primary, #e5e7eb);
    border-radius: var(--radius-lg, 8px);
    background: var(--background-fill-primary, white);
    overflow: hidden;
  }
  .command-header {
    display: flex;
    align-items: baseline;
    gap: 12px;
    padding: 10px 14px 0;
  }
  .command-title {
    font-size: var(--text-md, 14px);
    font-weight: 500;
    color: var(--body-text-color, #1f2937);
    white-space: nowrap;
  }
  .command-desc {
    font-size: var(--text-sm, 12px);
    color: var(--body-text-color-subdued, #6b7280);
  }
  .command-body {
    display: flex;
    align-items: flex-start;
    gap: 8px;
    padding: 8px 14px 10px;
  }
  .command-body.code-block {
    padding: 0;
    background: var(--background-fill-secondary, #f9fafb);
    position: relative;
  }
  .command-code {
    flex: 1;
    font-family: "SFMono-Regular", "Consolas", "Liberation Mono", "Menlo", monospace;
    font-size: 12px;
    color: var(--body-text-color, #1f2937);
    background: var(--background-fill-secondary, #f9fafb);
    padding: 6px 8px;
    border-radius: var(--radius-sm, 3px);
    word-break: break-all;
    line-height: 1.5;
  }
  .code-block .command-code {
    padding: 12px 14px;
    border-radius: 0;
    background: none;
    white-space: pre;
    word-break: normal;
    overflow-x: auto;
    margin: 0;
  }
  .copy-btn {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 28px;
    height: 28px;
    flex-shrink: 0;
    border: none;
    background: none;
    border-radius: var(--radius-md, 4px);
    color: var(--body-text-color-subdued, #6b7280);
    cursor: pointer;
    transition: background-color 0.15s, color 0.15s;
  }
  .copy-btn:hover {
    background: var(--background-fill-secondary, #f3f4f6);
    color: var(--body-text-color, #1f2937);
  }
  .code-copy-btn {
    position: absolute;
    top: 8px;
    right: 8px;
  }
</style>
