<script>
  import LoadingTrackio from "../components/LoadingTrackio.svelte";
  import WaveformAudio from "../components/WaveformAudio.svelte";
  import { getLogs, getMediaUrl, isStaticMode, fetchMediaBlob } from "../lib/api.js";
  import { buildColorMap } from "../lib/stores.js";

  let {
    project = null,
    selectedRuns = [],
    allRuns = [],
    tableTruncateLength = 250,
  } = $props();

  let runColorMap = $derived(
    buildColorMap(allRuns.length ? allRuns : selectedRuns),
  );

  function runColor(item) {
    return runColorMap[item._runId] ?? runColorMap[item._run] ?? "#9ca3af";
  }

  let mediaItems = $state({ images: [], videos: [], audios: [], tables: [] });
  let loading = $state(false);

  async function loadMedia() {
    if (!project || selectedRuns.length === 0) {
      mediaItems = { images: [], videos: [], audios: [], tables: [] };
      return;
    }

    loading = true;
    try {
      const runsToLoad = selectedRuns;
      const allLogs = [];
      for (const run of runsToLoad) {
        const logs = await getLogs(project, run);
        if (logs)
          allLogs.push(
            ...logs.map((l) => ({
              ...l,
              _run: run.name,
              _runId: run.id ?? run.name,
            })),
          );
      }
      const logs = allLogs;
      const images = [];
      const videos = [];
      const audios = [];
      const tables = [];

      if (logs) {
        logs.forEach((log, step) => {
          Object.entries(log).forEach(([key, value]) => {
            if (value && typeof value === "object" && value._type) {
              const item = {
                key,
                step: log.step || step,
                _run: log._run,
                _runId: log._runId,
                ...value,
              };
              switch (value._type) {
                case "trackio.image":
                  images.push(item);
                  break;
                case "trackio.video":
                  videos.push(item);
                  break;
                case "trackio.audio":
                  audios.push(item);
                  break;
                case "trackio.table":
                  tables.push(item);
                  break;
              }
            }
          });
        });
      }

      if (await isStaticMode()) {
        const resolveAll = (items) =>
          Promise.all(
            items.map(async (item) => {
              if (item.file_path) {
                item._resolvedUrl = await fetchMediaBlob(item.file_path);
              }
              return item;
            }),
          );
        const tableImageItems = [];
        for (const tbl of tables) {
          if (!Array.isArray(tbl._value)) continue;
          for (const row of tbl._value) {
            for (const value of Object.values(row)) {
              if (value && typeof value === "object" && !Array.isArray(value) && value._type === "trackio.image") {
                tableImageItems.push(value);
              } else if (Array.isArray(value)) {
                for (const v of value) {
                  if (v && typeof v === "object" && v._type === "trackio.image") {
                    tableImageItems.push(v);
                  }
                }
              }
            }
          }
        }
        await Promise.all([
          resolveAll(images),
          resolveAll(videos),
          resolveAll(audios),
          resolveAll(tableImageItems),
        ]);
      }

      mediaItems = { images, videos, audios, tables };
    } catch (e) {
      console.error("Failed to load media:", e);
    } finally {
      loading = false;
    }
  }

  $effect(() => {
    project;
    selectedRuns;
    loadMedia();
  });

  function getFilePath(item) {
    if (item._resolvedUrl) return item._resolvedUrl;
    if (item.file_path) return getMediaUrl(item.file_path);
    return "";
  }

  function isImageCell(cell) {
    return (
      cell &&
      typeof cell === "object" &&
      !Array.isArray(cell) &&
      cell._type === "trackio.image"
    );
  }

  function isImageList(cell) {
    return (
      Array.isArray(cell) &&
      cell.length > 0 &&
      cell.every((v) => v && typeof v === "object" && v._type === "trackio.image")
    );
  }
</script>

<div class="media-page">
  {#if loading}
    <LoadingTrackio />
  {:else if mediaItems.images.length === 0 && mediaItems.videos.length === 0 && mediaItems.audios.length === 0 && mediaItems.tables.length === 0}
    <div class="empty-state">
      {#if !project}
        <h2>Select a project</h2>
        <p>Pick a project in the sidebar to browse media and tables for a run.</p>
      {:else if selectedRuns.length === 0}
        <h2>No runs selected</h2>
        <p>Select runs in the sidebar to browse media and tables.</p>
        <pre><code>{'import trackio\ntrackio.init(project="my-project")\ntrackio.log({"loss": 0.5})\ntrackio.finish()'}</code></pre>
      {:else}
        <h2>No media or tables in this run</h2>
        <p>Log images, video, audio, and tables by passing Trackio objects to <code>trackio.log()</code>:</p>
        <pre><code>{'import trackio\n\ntrackio.init(project="my-project")\ntrackio.log({"plot": trackio.Image("figure.png")})\ntrackio.log({"clip": trackio.Video("output.mp4")})\ntrackio.log({"audio": trackio.Audio("speech.wav")})\n\nimport pandas as pd\ndf = pd.DataFrame({"epoch": [0, 1], "acc": [0.9, 0.95]})\ntrackio.log({"samples": trackio.Table(dataframe=df)})'}</code></pre>
        <p>Each type appears in its own section here once logged.</p>
      {/if}
    </div>
  {:else}
    {#snippet meta(item)}
      <div class="meta">
        <span class="run-dot" style:background={runColor(item)}></span>
        <span class="meta-text">Run: {item._run}, Step: {item.step}</span>
      </div>
    {/snippet}
    {#if mediaItems.images.length > 0}
      <details class="section" open>
        <summary class="section-summary">
          <svg class="chevron" width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden="true">
            <path d="M3 4.5L6 7.5L9 4.5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
          </svg>
          <span class="section-title">Images ({mediaItems.images.length})</span>
        </summary>
        <div class="gallery">
          {#each mediaItems.images as img}
            <div class="gallery-item">
              <div class="media-label">{img.key}</div>
              <img src={getFilePath(img)} alt={img.caption || img.key} loading="lazy" />
              {#if img.caption}
                <div class="caption">{img.caption}</div>
              {/if}
              {@render meta(img)}
            </div>
          {/each}
        </div>
      </details>
    {/if}

    {#if mediaItems.videos.length > 0}
      <details class="section" open>
        <summary class="section-summary">
          <svg class="chevron" width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden="true">
            <path d="M3 4.5L6 7.5L9 4.5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
          </svg>
          <span class="section-title">Videos ({mediaItems.videos.length})</span>
        </summary>
        <div class="gallery">
          {#each mediaItems.videos as vid}
            <div class="gallery-item">
              <div class="media-label">{vid.key}</div>
              <video controls src={getFilePath(vid)} preload="metadata">
                <track kind="captions" />
              </video>
              {@render meta(vid)}
            </div>
          {/each}
        </div>
      </details>
    {/if}

    {#if mediaItems.audios.length > 0}
      <details class="section" open>
        <summary class="section-summary">
          <svg class="chevron" width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden="true">
            <path d="M3 4.5L6 7.5L9 4.5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
          </svg>
          <span class="section-title">Audio ({mediaItems.audios.length})</span>
        </summary>
        <div class="gallery">
          {#each mediaItems.audios as aud}
            <div class="gallery-item audio-gallery-item">
              <div class="media-label">{aud.key}</div>
              <WaveformAudio src={getFilePath(aud)} />
              {@render meta(aud)}
            </div>
          {/each}
        </div>
      </details>
    {/if}

    {#if mediaItems.tables.length > 0}
      <details class="section" open>
        <summary class="section-summary">
          <svg class="chevron" width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden="true">
            <path d="M3 4.5L6 7.5L9 4.5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
          </svg>
          <span class="section-title">Tables ({mediaItems.tables.length})</span>
        </summary>
        {#each mediaItems.tables as tbl}
          {#if tbl._value && tbl._value.length > 0}
            <div class="table-section">
              <div class="table-header">
                <div class="media-label">{tbl.key}</div>
                {@render meta(tbl)}
              </div>
              <table class="runs-table">
                <thead>
                  <tr>
                    {#each Object.keys(tbl._value[0]) as header}
                      <th>{header}</th>
                    {/each}
                  </tr>
                </thead>
                <tbody>
                  {#each tbl._value as row}
                    <tr>
                      {#each Object.values(row) as cell}
                        <td>
                          {#if isImageCell(cell)}
                            <img
                              class="table-image"
                              src={getFilePath(cell)}
                              alt={cell.caption || ""}
                              loading="lazy"
                            />
                          {:else if isImageList(cell)}
                            <div class="table-image-list">
                              {#each cell as img}
                                <img
                                  class="table-image"
                                  src={getFilePath(img)}
                                  alt={img.caption || ""}
                                  loading="lazy"
                                />
                              {/each}
                            </div>
                          {:else}
                            {typeof cell === "string" && cell.length > tableTruncateLength
                              ? cell.slice(0, tableTruncateLength) + "…"
                              : (cell ?? "")}
                          {/if}
                        </td>
                      {/each}
                    </tr>
                  {/each}
                </tbody>
              </table>
            </div>
          {/if}
        {/each}
      </details>
    {/if}
  {/if}
</div>

<style>
  .media-page {
    padding: 20px 24px;
    overflow-y: auto;
    flex: 1;
  }
  .section {
    margin: 16px 0;
  }
  .section-summary {
    display: flex;
    align-items: center;
    gap: 6px;
    cursor: pointer;
    list-style: none;
    user-select: none;
    padding: 4px 0;
    margin-bottom: 8px;
  }
  .section-summary::-webkit-details-marker {
    display: none;
  }
  .chevron {
    color: var(--body-text-color-subdued, #6b7280);
    transform: rotate(-90deg);
    transition: transform 0.15s ease;
    flex-shrink: 0;
  }
  details[open] > .section-summary .chevron {
    transform: rotate(0deg);
  }
  .section-title {
    font-size: var(--text-lg, 16px);
    font-weight: 600;
    color: var(--body-text-color, #1f2937);
  }
  .media-label {
    font-size: var(--text-sm, 12px);
    font-weight: 500;
    color: var(--body-text-color, #1f2937);
    word-break: break-word;
  }
  .meta {
    display: flex;
    align-items: center;
    gap: 3px;
    font-size: var(--text-xs, 11px);
    color: var(--body-text-color-subdued, #9ca3af);
    font-variant-numeric: tabular-nums;
  }
  .meta .run-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    flex-shrink: 0;
    margin: 0 2px;
  }
  .meta-text {
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .table-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    margin-bottom: 6px;
  }
  .runs-table {
    width: 100%;
    border-collapse: collapse;
    font-size: var(--text-md, 14px);
  }
  .runs-table th {
    text-align: left;
    padding: 8px 12px;
    border-bottom: 2px solid var(--border-color-primary, #e5e7eb);
    color: var(--body-text-color-subdued, #6b7280);
    font-weight: 600;
    font-size: var(--text-sm, 12px);
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }
  .runs-table td {
    padding: 8px 12px;
    border-bottom: 1px solid var(--border-color-primary, #e5e7eb);
    color: var(--body-text-color, #1f2937);
  }
  .runs-table tbody tr:nth-child(odd) {
    background: var(--table-odd-background-fill, var(--background-fill-primary, white));
  }
  .runs-table tbody tr:nth-child(even) {
    background: var(--table-even-background-fill, var(--background-fill-secondary, #f9fafb));
  }
  .runs-table tr:hover {
    background: var(--background-fill-secondary, #f3f4f6);
  }
  .table-image {
    max-height: 80px;
    max-width: 120px;
    border-radius: var(--radius-sm, 4px);
    display: block;
    object-fit: contain;
  }
  .table-image-list {
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
  }
  .gallery {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
    gap: 12px;
  }
  .gallery-item {
    display: flex;
    flex-direction: column;
    gap: 6px;
    padding: 8px;
    border: 1px solid var(--border-color-primary, #e5e7eb);
    border-radius: var(--radius-lg, 8px);
    background: var(--background-fill-secondary, #f9fafb);
    overflow: hidden;
  }
  .gallery-item img,
  .gallery-item video {
    width: 100%;
    display: block;
    border-radius: var(--radius-sm, 4px);
  }
  .audio-gallery-item {
    justify-content: space-between;
  }
  .caption {
    font-size: var(--text-sm, 12px);
    color: var(--body-text-color-subdued, #9ca3af);
  }
  .table-section {
    margin-bottom: 16px;
    overflow-x: auto;
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
  .empty-state pre {
    background: var(--background-fill-secondary, #f9fafb);
    padding: 16px;
    border-radius: var(--radius-lg, 8px);
    border: 1px solid var(--border-color-primary, #e5e7eb);
    font-size: 13px;
    overflow-x: auto;
  }
  .empty-state code {
    background: var(--background-fill-secondary, #f0f0f0);
    padding: 1px 5px;
    border-radius: var(--radius-sm, 4px);
    font-size: 13px;
  }
  .empty-state pre code {
    background: none;
    padding: 0;
  }
</style>
