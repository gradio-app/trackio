<script>
  import GradioTable from "../components/GradioTable.svelte";
  import LoadingTrackio from "../components/LoadingTrackio.svelte";
  import { getLogs, getMediaUrl, isStaticMode, fetchMediaBlob } from "../lib/api.js";

  let { project = null, selectedRuns = [], tableTruncateLength = 250 } = $props();

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
        if (logs) allLogs.push(...logs.map((l) => ({ ...l, _run: run.name })));
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
        await Promise.all([
          resolveAll(images),
          resolveAll(videos),
          resolveAll(audios),
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
                rows={tbl._value.map(row => Object.values(row).map(v =>
                  typeof v === "string" && v.length > tableTruncateLength
                    ? v.slice(0, tableTruncateLength) + "…"
                    : v
                ))}
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
