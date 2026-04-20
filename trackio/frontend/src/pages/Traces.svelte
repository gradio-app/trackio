<script>
  import LoadingTrackio from "../components/LoadingTrackio.svelte";
  import { getMediaUrl, getTraces } from "../lib/api.js";

  let {
    project = null,
    selectedRuns = [],
  } = $props();

  let loading = $state(false);
  let search = $state("");
  let sortBy = $state("request_time_desc");
  let expandedTraceId = $state(null);
  let traces = $state([]);

  function textFromContent(content) {
    if (typeof content === "string") return content;
    if (Array.isArray(content)) {
      return content
        .map((part) => {
          if (typeof part === "string") return part;
          if (typeof part?.text === "string") return part.text;
          if (typeof part?.content === "string") return part.content;
          if (part?._type === "trackio.image" || part?.type === "image") return "[image]";
          return "";
        })
        .filter(Boolean)
        .join(" ");
    }
    if (typeof content?.text === "string") return content.text;
    return "";
  }

  function normalizeTrace(trace, runLabel) {
    const messages = Array.isArray(trace.messages) ? trace.messages : [];
    const firstUser = messages.find((message) => message?.role === "user");
    const firstAssistant = messages.find((message) => message?.role === "assistant");
    return {
      ...trace,
      run: trace.run || runLabel,
      request: textFromContent(firstUser?.content) || "(no user message)",
      preview: textFromContent(firstAssistant?.content) || "(no assistant response)",
    };
  }

  async function loadTraces() {
    if (!project || selectedRuns.length === 0) {
      traces = [];
      expandedTraceId = null;
      return;
    }

    loading = true;
    try {
      const batches = await Promise.all(
        selectedRuns.map(async (run) => {
          const runTraces = await getTraces(project, run);
          return runTraces.map((trace) => normalizeTrace(trace, run.name));
        }),
      );
      traces = batches.flat();
      if (!traces.find((trace) => trace.id === expandedTraceId)) {
        expandedTraceId = null;
      }
    } catch (error) {
      console.error("Failed to load traces:", error);
      traces = [];
    } finally {
      loading = false;
    }
  }

  let visibleTraces = $derived.by(() => {
    const needle = search.trim().toLowerCase();
    const filtered = traces.filter((trace) => {
      if (!needle) return true;
      const haystack = [
        trace.id,
        trace.key,
        trace.run,
        trace.request,
        trace.preview,
        JSON.stringify(trace.metadata || {}),
        ...trace.messages.map((message) => {
          if (typeof message?.content === "string") return message.content;
          return JSON.stringify(message?.content || "");
        }),
      ]
        .join(" ")
        .toLowerCase();
      return haystack.includes(needle);
    });

    return filtered.sort((left, right) => {
      switch (sortBy) {
        case "step_asc":
          return (left.step ?? 0) - (right.step ?? 0);
        case "step_desc":
          return (right.step ?? 0) - (left.step ?? 0);
        case "request_time_asc":
          return String(left.timestamp || "").localeCompare(String(right.timestamp || ""));
        case "request_time_desc":
        default:
          return String(right.timestamp || "").localeCompare(String(left.timestamp || ""));
      }
    });
  });

  $effect(() => {
    project;
    selectedRuns;
    loadTraces();
  });

  function toggleTrace(traceId) {
    expandedTraceId = expandedTraceId === traceId ? null : traceId;
  }

  function formatRelativeTime(timestamp) {
    if (!timestamp) return "—";
    const then = new Date(timestamp);
    if (Number.isNaN(then.getTime())) return timestamp;

    const now = new Date();
    const diffMs = now.getTime() - then.getTime();
    const diffSeconds = Math.max(0, Math.round(diffMs / 1000));

    if (diffSeconds < 5) return "just now";
    if (diffSeconds < 60) return `${diffSeconds} sec ago`;

    const diffMinutes = Math.round(diffSeconds / 60);
    if (diffMinutes < 60) return `${diffMinutes} min ago`;

    const diffHours = Math.round(diffMinutes / 60);
    if (diffHours < 24) return `${diffHours} hr ago`;

    const diffDays = Math.round(diffHours / 24);
    if (diffDays < 7) return `${diffDays} day${diffDays === 1 ? "" : "s"} ago`;

    const diffWeeks = Math.round(diffDays / 7);
    if (diffWeeks < 5) return `${diffWeeks} wk ago`;

    const diffMonths = Math.round(diffDays / 30);
    if (diffMonths < 12) return `${diffMonths} mo ago`;

    const diffYears = Math.round(diffDays / 365);
    return `${diffYears} yr ago`;
  }

  function renderableParts(message) {
    const content = message?.content;
    if (typeof content === "string" || content == null) return [];
    if (Array.isArray(content)) return content;
    return [content];
  }

  function hasRenderableParts(message) {
    return renderableParts(message).length > 0;
  }

  function isImagePart(part) {
    return (
      part?._type === "trackio.image" ||
      part?.type === "image" ||
      part?.type === "input_image" ||
      part?.type === "image_url"
    );
  }

  function imageSrc(part) {
    if (part?.file_path) return getMediaUrl(part.file_path);
    if (part?.image_url?.url) return part.image_url.url;
    if (typeof part?.url === "string") return part.url;
    return "";
  }

  function imageAlt(part) {
    return part?.caption || part?.alt || "Trace image";
  }

  function longText(text) {
    return typeof text === "string" && text.length > 500;
  }

  function metadataEntries(trace) {
    return Object.entries(trace.metadata || {});
  }
</script>

<div class="traces-page">
  {#if loading}
    <LoadingTrackio />
  {:else if !project}
    <div class="empty-state">
      <h2>Select a project</h2>
      <p>Pick a project to browse trace logs.</p>
    </div>
  {:else if selectedRuns.length === 0}
    <div class="empty-state">
      <h2>No runs selected</h2>
      <p>Select one or more runs in the sidebar to browse traces.</p>
    </div>
  {:else if visibleTraces.length === 0}
    <div class="toolbar">
      <div class="search-wrap">
        <input type="text" bind:value={search} placeholder="Search traces by request" />
      </div>
      <label class="sort-wrap">
        <span>Sort:</span>
        <select bind:value={sortBy}>
          <option value="request_time_desc">Request time</option>
          <option value="request_time_asc">Oldest first</option>
          <option value="step_desc">Step descending</option>
          <option value="step_asc">Step ascending</option>
        </select>
      </label>
      <div class="count">0 of {traces.length}</div>
    </div>
    <div class="empty-state">
      <h2>No traces match the current filters</h2>
      <p>Try a different search query or model filter.</p>
    </div>
  {:else}
    <div class="toolbar">
      <div class="search-wrap">
        <input type="text" bind:value={search} placeholder="Search traces by request" />
      </div>
      <label class="sort-wrap">
        <span>Sort:</span>
        <select bind:value={sortBy}>
          <option value="request_time_desc">Request time</option>
          <option value="request_time_asc">Oldest first</option>
          <option value="step_desc">Step descending</option>
          <option value="step_asc">Step ascending</option>
        </select>
      </label>
      <div class="count">{visibleTraces.length} of {traces.length}</div>
    </div>

    <div class="traces-table-wrap">
      <table class="traces-table">
        <thead>
          <tr>
            <th>Trace ID</th>
            <th>Request</th>
            <th>Run</th>
            <th>Step</th>
            <th>Request time</th>
          </tr>
        </thead>
        <tbody>
          {#each visibleTraces as trace}
            <tr class="trace-row" onclick={() => toggleTrace(trace.id)}>
              <td class="trace-id-cell">
                <span class="trace-id">{trace.id}</span>
              </td>
              <td class="request-cell">
                <div class="request">{trace.request}</div>
                <div class="preview">{trace.preview}</div>
              </td>
              <td>{trace.run || "—"}</td>
              <td>{trace.step ?? "—"}</td>
              <td>{formatRelativeTime(trace.timestamp)}</td>
            </tr>
            {#if expandedTraceId === trace.id}
              <tr class="expanded-row">
                <td colspan="5">
                  <div class="trace-detail">
                    <div class="detail-meta">
                      <span>Logged as: {trace.key}</span>
                      <span>Timestamp: {trace.timestamp || "—"}</span>
                      {#each metadataEntries(trace) as [key, value]}
                        <span>{key}: {value}</span>
                      {/each}
                    </div>

                    <div class="conversation">
                      {#each trace.messages as message}
                        <div class="message" data-role={message.role || "unknown"}>
                          <div class="message-role">
                            {message.role || "message"}
                            {#if message.tool_calls?.length}
                              <span class="message-tag">tool calls</span>
                            {/if}
                            {#if message.function_call}
                              <span class="message-tag">function call</span>
                            {/if}
                          </div>

                          {#if typeof message.content === "string"}
                            {#if longText(message.content)}
                              <details class="message-details">
                                <summary>Expand content</summary>
                                <pre class="message-content">{message.content}</pre>
                              </details>
                            {:else}
                              <pre class="message-content">{message.content}</pre>
                            {/if}
                          {:else if hasRenderableParts(message)}
                            <div class="message-parts">
                              {#each renderableParts(message) as part}
                                {#if isImagePart(part)}
                                  <img class="trace-image" src={imageSrc(part)} alt={imageAlt(part)} />
                                {:else}
                                  <pre class="message-content">{JSON.stringify(part, null, 2)}</pre>
                                {/if}
                              {/each}
                            </div>
                          {/if}

                          {#if message.tool_calls?.length}
                            <div class="tool-blocks">
                              {#each message.tool_calls as toolCall}
                                <pre class="tool-block">{JSON.stringify(toolCall, null, 2)}</pre>
                              {/each}
                            </div>
                          {/if}

                          {#if message.function_call}
                            <pre class="tool-block">{JSON.stringify(message.function_call, null, 2)}</pre>
                          {/if}
                        </div>
                      {/each}
                    </div>
                  </div>
                </td>
              </tr>
            {/if}
          {/each}
        </tbody>
      </table>
    </div>
  {/if}
</div>

<style>
  .traces-page {
    padding: 20px 24px;
    overflow-y: auto;
    flex: 1;
    background: var(--background-fill-primary, white);
  }
  .toolbar {
    display: flex;
    align-items: center;
    gap: 12px;
    margin-bottom: 16px;
  }
  .search-wrap {
    flex: 1;
  }
  .search-wrap input,
  .sort-wrap select {
    width: 100%;
    border: 1px solid var(--border-color-primary, #e5e7eb);
    border-radius: var(--radius-md, 6px);
    background: var(--background-fill-primary, white);
    color: var(--body-text-color, #1f2937);
    font-size: 14px;
    padding: 10px 12px;
    font-family: inherit;
  }
  .sort-wrap {
    display: flex;
    align-items: center;
    gap: 8px;
    color: var(--body-text-color, #1f2937);
    font-size: 14px;
    white-space: nowrap;
  }
  .count {
    margin-left: auto;
    color: var(--body-text-color-subdued, #6b7280);
    font-size: 14px;
    white-space: nowrap;
  }
  .traces-table-wrap {
    border: 1px solid var(--border-color-primary, #e5e7eb);
    border-radius: var(--radius-lg, 8px);
    overflow: hidden;
  }
  .traces-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 14px;
  }
  .traces-table th {
    text-align: left;
    padding: 10px 12px;
    border-bottom: 1px solid var(--border-color-primary, #e5e7eb);
    color: var(--body-text-color-subdued, #6b7280);
    font-weight: 600;
    font-size: 12px;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    background: var(--background-fill-primary, white);
  }
  .traces-table td {
    padding: 10px 12px;
    border-bottom: 1px solid var(--border-color-primary, #e5e7eb);
    color: var(--body-text-color, #1f2937);
    vertical-align: top;
  }
  .trace-row {
    cursor: pointer;
  }
  .trace-row:hover {
    background: var(--background-fill-secondary, #f9fafb);
  }
  .trace-id {
    display: inline-block;
    background: var(--background-fill-secondary, #f3f4f6);
    color: var(--body-text-color, #1f2937);
    border: 1px solid var(--border-color-primary, #e5e7eb);
    border-radius: var(--radius-md, 6px);
    padding: 6px 10px;
    font-size: 13px;
    word-break: break-all;
    line-height: 1.35;
  }
  .request {
    font-weight: 500;
    margin-bottom: 4px;
  }
  .preview {
    color: var(--body-text-color-subdued, #6b7280);
    font-size: 13px;
    line-height: 1.45;
  }
  .expanded-row td {
    padding: 0;
    background: var(--background-fill-secondary, #fafafa);
  }
  .trace-detail {
    padding: 16px 18px 18px;
  }
  .detail-meta {
    display: flex;
    gap: 16px;
    flex-wrap: wrap;
    color: var(--body-text-color-subdued, #6b7280);
    font-size: 13px;
    margin-bottom: 14px;
  }
  .conversation {
    display: flex;
    flex-direction: column;
    gap: 12px;
  }
  .message {
    border: 1px solid var(--border-color-primary, #e5e7eb);
    border-radius: var(--radius-md, 6px);
    background: var(--background-fill-primary, white);
    padding: 12px;
  }
  .message-role {
    margin-bottom: 8px;
    color: var(--body-text-color-subdued, #6b7280);
    font-size: 12px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    display: flex;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;
  }
  .message-tag {
    border: 1px solid var(--border-color-primary, #e5e7eb);
    border-radius: 999px;
    padding: 2px 8px;
    font-size: 11px;
    font-weight: 500;
    text-transform: none;
    letter-spacing: 0;
  }
  .message-content,
  .tool-block {
    margin: 0;
    white-space: pre-wrap;
    word-break: break-word;
    font-family: inherit;
    color: var(--body-text-color, #1f2937);
    line-height: 1.5;
  }
  .message-details summary {
    cursor: pointer;
    margin-bottom: 8px;
    color: var(--body-text-color-subdued, #6b7280);
  }
  .tool-blocks {
    display: flex;
    flex-direction: column;
    gap: 8px;
    margin-top: 10px;
  }
  .tool-block {
    background: var(--background-fill-secondary, #f9fafb);
    border-radius: var(--radius-md, 6px);
    padding: 10px;
    overflow-x: auto;
  }
  .message-parts {
    display: flex;
    flex-direction: column;
    gap: 10px;
  }
  .trace-image {
    max-width: 100%;
    max-height: 360px;
    border: 1px solid var(--border-color-primary, #e5e7eb);
    border-radius: var(--radius-md, 6px);
  }
  .empty-state {
    max-width: 640px;
    padding: 40px 24px;
    color: var(--body-text-color, #1f2937);
  }
  .empty-state h2 {
    margin: 0 0 8px;
    font-size: 20px;
    font-weight: 700;
  }
  .empty-state p {
    margin: 12px 0 8px;
    color: var(--body-text-color-subdued, #6b7280);
  }
  @media (max-width: 1100px) {
    .toolbar {
      flex-wrap: wrap;
    }
    .count {
      margin-left: 0;
    }
  }
</style>
