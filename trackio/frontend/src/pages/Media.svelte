<script>
  import { getLogs, getRunsForProject, getMediaUrl } from "../lib/api.js";

  let { project = null, runs = [] } = $props();

  let selectedRun = $state(null);
  let mediaItems = $state({ images: [], videos: [], audios: [], tables: [] });
  let loading = $state(false);

  $effect(() => {
    if (runs.length > 0 && !selectedRun) {
      selectedRun = runs[runs.length - 1];
    }
  });

  async function loadMedia() {
    if (!project || !selectedRun) {
      mediaItems = { images: [], videos: [], audios: [], tables: [] };
      return;
    }

    loading = true;
    try {
      const logs = await getLogs(project, selectedRun);
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

      mediaItems = { images, videos, audios, tables };
    } catch (e) {
      console.error("Failed to load media:", e);
    } finally {
      loading = false;
    }
  }

  $effect(() => {
    project;
    selectedRun;
    loadMedia();
  });

  function getFilePath(item) {
    if (item.file_path) {
      return getMediaUrl(item.file_path);
    }
    return "";
  }
</script>

<div class="media-page">
  <div class="controls">
    <label class="label">Run</label>
    <select class="select" bind:value={selectedRun}>
      {#each runs as run}
        <option value={run}>{run}</option>
      {/each}
    </select>
  </div>

  {#if loading}
    <div class="loading">Loading media...</div>
  {:else if mediaItems.images.length === 0 && mediaItems.videos.length === 0 && mediaItems.audios.length === 0 && mediaItems.tables.length === 0}
    <div class="empty-state">No media or tables found for this run.</div>
  {:else}
    {#if mediaItems.images.length > 0}
      <section>
        <h3 class="section-title">Images ({mediaItems.images.length})</h3>
        <div class="gallery">
          {#each mediaItems.images as img}
            <div class="gallery-item">
              <img src={getFilePath(img)} alt={img.caption || img.key} loading="lazy" />
              {#if img.caption}
                <div class="caption">{img.caption}</div>
              {/if}
              <div class="step-label">Step {img.step}</div>
            </div>
          {/each}
        </div>
      </section>
    {/if}

    {#if mediaItems.videos.length > 0}
      <section>
        <h3 class="section-title">Videos ({mediaItems.videos.length})</h3>
        <div class="gallery">
          {#each mediaItems.videos as vid}
            <div class="gallery-item">
              <video controls src={getFilePath(vid)} preload="metadata">
                <track kind="captions" />
              </video>
              <div class="step-label">Step {vid.step}</div>
            </div>
          {/each}
        </div>
      </section>
    {/if}

    {#if mediaItems.audios.length > 0}
      <section>
        <h3 class="section-title">Audio ({mediaItems.audios.length})</h3>
        <div class="audio-list">
          {#each mediaItems.audios as aud}
            <div class="audio-item">
              <span class="audio-label">{aud.key} (step {aud.step})</span>
              <audio controls src={getFilePath(aud)} preload="metadata">
                <track kind="captions" />
              </audio>
            </div>
          {/each}
        </div>
      </section>
    {/if}

    {#if mediaItems.tables.length > 0}
      <section>
        <h3 class="section-title">Tables ({mediaItems.tables.length})</h3>
        {#each mediaItems.tables as tbl}
          <div class="table-container">
            <h4>{tbl.key} (step {tbl.step})</h4>
            {#if tbl._value && tbl._value.length > 0}
              <table class="data-table">
                <thead>
                  <tr>
                    {#each Object.keys(tbl._value[0]) as col}
                      <th>{col}</th>
                    {/each}
                  </tr>
                </thead>
                <tbody>
                  {#each tbl._value as row}
                    <tr>
                      {#each Object.values(row) as cell}
                        <td>
                          {#if typeof cell === "object" && cell?._type?.startsWith("trackio.")}
                            <img
                              src={getFilePath(cell)}
                              alt="media"
                              class="table-media"
                            />
                          {:else}
                            {cell ?? ""}
                          {/if}
                        </td>
                      {/each}
                    </tr>
                  {/each}
                </tbody>
              </table>
            {/if}
          </div>
        {/each}
      </section>
    {/if}
  {/if}
</div>

<style>
  .media-page {
    padding: 16px;
    overflow-y: auto;
    flex: 1;
  }
  .controls {
    margin-bottom: 16px;
    max-width: 300px;
  }
  .label {
    display: block;
    font-size: 13px;
    font-weight: 500;
    color: var(--text-primary);
    margin-bottom: 4px;
  }
  .select {
    width: 100%;
    padding: 6px 8px;
    border: 1px solid var(--input-border);
    border-radius: var(--radius-sm);
    background: var(--input-bg);
    color: var(--text-primary);
    font-size: 13px;
  }
  .section-title {
    font-size: 15px;
    font-weight: 600;
    color: var(--text-primary);
    margin: 16px 0 8px;
  }
  .gallery {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
    gap: 12px;
  }
  .gallery-item {
    border: 1px solid var(--border-color);
    border-radius: var(--radius-md);
    overflow: hidden;
    background: var(--bg-secondary);
  }
  .gallery-item img,
  .gallery-item video {
    width: 100%;
    display: block;
  }
  .caption {
    padding: 4px 8px;
    font-size: 12px;
    color: var(--text-secondary);
  }
  .step-label {
    padding: 4px 8px;
    font-size: 11px;
    color: var(--text-muted);
  }
  .audio-list {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  .audio-item {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 8px;
    border: 1px solid var(--border-color);
    border-radius: var(--radius-sm);
  }
  .audio-label {
    font-size: 12px;
    color: var(--text-secondary);
    min-width: 120px;
  }
  .table-container {
    margin-bottom: 16px;
  }
  .table-container h4 {
    font-size: 13px;
    color: var(--text-primary);
    margin-bottom: 8px;
  }
  .data-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 12px;
  }
  .data-table th,
  .data-table td {
    padding: 6px 10px;
    border: 1px solid var(--border-color);
    text-align: left;
  }
  .data-table th {
    background: var(--bg-secondary);
    font-weight: 600;
    color: var(--text-primary);
  }
  .data-table td {
    color: var(--text-secondary);
  }
  .table-media {
    max-width: 100px;
    max-height: 60px;
  }
  .loading,
  .empty-state {
    padding: 40px;
    text-align: center;
    color: var(--text-secondary);
  }
</style>
