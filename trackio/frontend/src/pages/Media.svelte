<script>
  import GradioTable from "../components/GradioTable.svelte";
  import { getLogs, getMediaUrl } from "../lib/api.js";

  let { project = null, selectedRun = $bindable(null) } = $props();

  let mediaItems = $state({ images: [], videos: [], audios: [], tables: [] });
  let loading = $state(false);

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
          <div class="table-section">
            {#if tbl._value && tbl._value.length > 0}
              <GradioTable
                label="{tbl.key} (step {tbl.step})"
                headers={Object.keys(tbl._value[0])}
                rows={tbl._value.map(row => Object.values(row))}
              />
            {/if}
          </div>
        {/each}
      </section>
    {/if}
  {/if}
</div>

<style>
  .media-page {
    padding: 20px 24px;
    overflow-y: auto;
    flex: 1;
  }
  .section-title {
    font-size: var(--text-lg, 16px);
    font-weight: 600;
    color: var(--body-text-color, #1f2937);
    margin: 16px 0 8px;
  }
  .gallery {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
    gap: 12px;
  }
  .gallery-item {
    border: 1px solid var(--border-color-primary, #e5e7eb);
    border-radius: var(--radius-lg, 8px);
    overflow: hidden;
    background: var(--background-fill-secondary, #f9fafb);
  }
  .gallery-item img,
  .gallery-item video {
    width: 100%;
    display: block;
  }
  .caption {
    padding: 4px 8px;
    font-size: var(--text-sm, 12px);
    color: var(--body-text-color-subdued, #9ca3af);
  }
  .step-label {
    padding: 4px 8px;
    font-size: var(--text-xs, 10px);
    color: var(--body-text-color-subdued, #9ca3af);
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
    border: 1px solid var(--border-color-primary, #e5e7eb);
    border-radius: var(--radius-lg, 8px);
  }
  .audio-label {
    font-size: var(--text-sm, 12px);
    color: var(--body-text-color-subdued, #9ca3af);
    min-width: 120px;
  }
  .table-section {
    margin-bottom: 16px;
  }
  .loading,
  .empty-state {
    padding: 40px;
    text-align: center;
    color: var(--body-text-color-subdued, #9ca3af);
  }
</style>
