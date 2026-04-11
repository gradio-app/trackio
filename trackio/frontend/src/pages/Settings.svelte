<script>
  import {
    getThemePreference,
    setThemePreference,
  } from "../lib/theme.js";

  let { spaceId = null, selectedProject = null } = $props();

  let themeChoice = $state(getThemePreference());
  let copiedIdx = $state(null);

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
      { title: "Launch dashboard", cmd: `trackio show` },
      { title: "Launch dashboard (project)", cmd: `trackio show --project "${proj}"` },
      { title: "List projects", cmd: `trackio${sf} list projects` },
      { title: "List runs", cmd: `trackio${sf} list runs --project "${proj}"` },
      { title: "List metrics", cmd: `trackio${sf} list metrics --project "${proj}" --run <run>` },
      { title: "Project summary", cmd: `trackio${sf} summary --project "${proj}"` },
      { title: "Run summary", cmd: `trackio${sf} summary --project "${proj}" --run <run>` },
      { title: "Sync to HF Space", cmd: `trackio sync --project "${proj}"` },
      { title: "Check sync status", cmd: `trackio status` },
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
    }
  }
</script>

<div class="settings-page">
  <div class="settings-content">
    <h2 class="page-title">Settings</h2>

    <section class="settings-section">
      <h3 class="section-title">Appearance</h3>
      <p class="section-desc">Choose how the dashboard looks to you.</p>
      <div class="theme-switcher">
        {#each [
          { value: "system", label: "System" },
          { value: "light", label: "Light" },
          { value: "dark", label: "Dark" },
        ] as opt}
          <button
            class="theme-option"
            class:selected={themeChoice === opt.value}
            onclick={() => switchTheme(opt.value)}
          >
            {opt.label}
          </button>
        {/each}
      </div>
    </section>

    <section class="settings-section">
      <h3 class="section-title">CLI Reference</h3>
      <p class="section-desc">
        Common Trackio CLI commands.
        {#if spaceId}
          Connected to <strong>{spaceId}</strong> — remote commands include <code>--space</code> automatically.
        {/if}
      </p>
      <div class="commands-table">
        {#each commands as cmd, i}
          <div class="command-row">
            <span class="command-label">{cmd.title}</span>
            <div class="command-value">
              <code>{cmd.cmd}</code>
              <button
                class="copy-btn"
                class:copied={copiedIdx === i}
                onclick={() => copyCommand(cmd.cmd, i)}
                title="Copy"
              >
                {#if copiedIdx === i}
                  <svg width="13" height="13" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M3.5 8.5l3 3 6-7" />
                  </svg>
                {:else}
                  <svg width="13" height="13" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
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
  </div>
</div>

<style>
  .settings-page {
    padding: 24px 32px;
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
    margin: 0 0 24px;
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
    display: inline-flex;
    border: 1px solid var(--border-color-primary, #e5e7eb);
    border-radius: var(--radius-lg, 8px);
    overflow: hidden;
  }
  .theme-option {
    padding: 8px 20px;
    border: none;
    background: var(--background-fill-primary, white);
    color: var(--body-text-color-subdued, #6b7280);
    font-size: var(--text-md, 14px);
    cursor: pointer;
    transition: all 0.15s;
    border-right: 1px solid var(--border-color-primary, #e5e7eb);
  }
  .theme-option:last-child {
    border-right: none;
  }
  .theme-option:hover {
    color: var(--body-text-color, #1f2937);
    background: var(--background-fill-secondary, #f9fafb);
  }
  .theme-option.selected {
    background: var(--color-accent, #f97316);
    color: white;
    font-weight: 500;
  }

  .commands-table {
    border: 1px solid var(--border-color-primary, #e5e7eb);
    border-radius: var(--radius-lg, 8px);
    overflow: hidden;
  }
  .command-row {
    display: flex;
    align-items: center;
    gap: 16px;
    padding: 10px 14px;
    border-bottom: 1px solid var(--border-color-primary, #e5e7eb);
  }
  .command-row:last-child {
    border-bottom: none;
  }
  .command-label {
    width: 180px;
    flex-shrink: 0;
    font-size: var(--text-sm, 12px);
    color: var(--body-text-color-subdued, #6b7280);
  }
  .command-value {
    flex: 1;
    display: flex;
    align-items: center;
    gap: 8px;
    min-width: 0;
  }
  .command-value code {
    flex: 1;
    font-family: "SFMono-Regular", "Consolas", "Liberation Mono", "Menlo", monospace;
    font-size: 12px;
    color: var(--body-text-color, #1f2937);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .copy-btn {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 26px;
    height: 26px;
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
  .copy-btn.copied {
    color: var(--color-accent, #f97316);
  }
</style>
