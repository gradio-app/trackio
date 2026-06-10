<script>
  import LoadingTrackio from "../components/LoadingTrackio.svelte";
  import WaveformAudio from "../components/WaveformAudio.svelte";
  import { getLogs, getMediaUrl } from "../lib/api.js";
  import { filterMetricsByRegex } from "../lib/dataProcessing.js";
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

  const PAGE_SIZE = 48;
  const EMPTY_MEDIA_ITEMS = { images: [], videos: [], audios: [], tables: [] };

  let rawMediaItems = $state(EMPTY_MEDIA_ITEMS);
  let sortOrder = $state("newest");
  let imageFilter = $state("");
  let visibleCounts = $state(createVisibleCounts());
  let selectedImage = $state(null);
  let selectedImageList = $state([]);
  let selectedImageIndex = $state(null);
  let loading = $state(false);

  function createVisibleCounts() {
    return {
      images: PAGE_SIZE,
      videos: PAGE_SIZE,
      audios: PAGE_SIZE,
      tables: PAGE_SIZE,
    };
  }

  function resetVisibleCounts() {
    visibleCounts = createVisibleCounts();
  }

  function compareMediaItems(a, b) {
    const aStep = Number.isFinite(a.step) ? a.step : 0;
    const bStep = Number.isFinite(b.step) ? b.step : 0;
    const stepDelta = sortOrder === "newest" ? bStep - aStep : aStep - bStep;
    if (stepDelta !== 0) return stepDelta;

    const aIndex = Number.isFinite(a._index) ? a._index : 0;
    const bIndex = Number.isFinite(b._index) ? b._index : 0;
    return sortOrder === "newest" ? bIndex - aIndex : aIndex - bIndex;
  }

  function sortMediaItems(items) {
    return [...items].sort(compareMediaItems);
  }

  function isDisplayableTable(item) {
    return Array.isArray(item._value) && item._value.length > 0;
  }

  let mediaItems = $derived.by(() => ({
    images: sortMediaItems(rawMediaItems.images),
    videos: sortMediaItems(rawMediaItems.videos),
    audios: sortMediaItems(rawMediaItems.audios),
    tables: sortMediaItems(rawMediaItems.tables.filter(isDisplayableTable)),
  }));

  function imageName(img) {
    return img.caption ? `${img.key} ${img.caption}` : img.key;
  }

  let filteredImages = $derived.by(() => {
    if (!imageFilter.trim()) return mediaItems.images;
    const matches = new Set(
      filterMetricsByRegex(
        mediaItems.images.map((img) => imageName(img)),
        imageFilter,
      ),
    );
    return mediaItems.images.filter((img) => matches.has(imageName(img)));
  });

  let visibleMediaItems = $derived.by(() => ({
    images: filteredImages.slice(0, visibleCounts.images),
    videos: mediaItems.videos.slice(0, visibleCounts.videos),
    audios: mediaItems.audios.slice(0, visibleCounts.audios),
    tables: mediaItems.tables.slice(0, visibleCounts.tables),
  }));

  let hasMedia = $derived(
    mediaItems.images.length > 0 ||
      mediaItems.videos.length > 0 ||
      mediaItems.audios.length > 0 ||
      mediaItems.tables.length > 0,
  );

  function showMore(type) {
    visibleCounts[type] += PAGE_SIZE;
  }

  $effect(() => {
    sortOrder;
    rawMediaItems;
    resetVisibleCounts();
  });

  async function loadMedia() {
    if (!project || selectedRuns.length === 0) {
      rawMediaItems = EMPTY_MEDIA_ITEMS;
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
      let mediaIndex = 0;

      if (logs) {
        logs.forEach((log, step) => {
          Object.entries(log).forEach(([key, value]) => {
            if (value && typeof value === "object" && value._type) {
              const item = {
                key,
                step: log.step ?? step,
                _index: mediaIndex++,
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

      rawMediaItems = { images, videos, audios, tables };
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

  function markImageLoaded(event) {
    event.currentTarget.parentElement?.classList.add("image-loaded");
  }

  function markImageFailed(event) {
    event.currentTarget.parentElement?.classList.add("image-failed");
  }

  function normalizeImage(image, parent = null) {
    return {
      ...image,
      key: image.key ?? parent?.key,
      step: image.step ?? parent?.step,
      _run: image._run ?? parent?._run,
      _runId: image._runId ?? parent?._runId,
      caption: image.caption ?? parent?.caption,
    };
  }

  function openImage(image, parent = null, imageList = [], index = null) {
    selectedImage = normalizeImage(image, parent);
    selectedImageList = imageList;
    selectedImageIndex = index;
  }

  function closeImage() {
    selectedImage = null;
    selectedImageList = [];
    selectedImageIndex = null;
  }

  function showImageAt(index) {
    if (index < 0 || index >= selectedImageList.length) return;
    selectedImage = normalizeImage(selectedImageList[index]);
    selectedImageIndex = index;
  }

  function showPreviousImage() {
    if (selectedImageIndex === null || selectedImageList.length <= 1) return;
    showImageAt(
      (selectedImageIndex - 1 + selectedImageList.length) % selectedImageList.length,
    );
  }

  function showNextImage() {
    if (selectedImageIndex === null || selectedImageList.length <= 1) return;
    showImageAt((selectedImageIndex + 1) % selectedImageList.length);
  }

  function handleKeydown(event) {
    if (!selectedImage) return;
    if (event.key === "Escape") closeImage();
    if (event.key === "ArrowLeft") showPreviousImage();
    if (event.key === "ArrowRight") showNextImage();
  }
</script>

<svelte:window onkeydown={handleKeydown} />

<div class="media-page">
  {#if loading}
    <LoadingTrackio />
  {:else if !hasMedia}
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
    <div class="media-toolbar">
      <label class="media-control" for="media-sort-order">
        <span>Sort</span>
        <select id="media-sort-order" bind:value={sortOrder}>
          <option value="newest">Newest first</option>
          <option value="oldest">Oldest first</option>
        </select>
      </label>
    </div>

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
        <div class="image-filter">
          <input
            type="text"
            bind:value={imageFilter}
            placeholder="Filter images..."
            aria-label="Filter images"
          />
        </div>
        <div class="gallery">
          {#each visibleMediaItems.images as img, i}
            <div class="gallery-item">
              <div class="media-label">{img.key}</div>
              <button
                class="image-frame"
                type="button"
                onclick={() => openImage(img, null, filteredImages, i)}
                aria-label={`Open ${img.caption || img.key}`}
              >
                <span class="image-placeholder">Loading image…</span>
                <img
                  src={getFilePath(img)}
                  alt={img.caption || img.key}
                  loading="lazy"
                  decoding="async"
                  onload={markImageLoaded}
                  onerror={markImageFailed}
                />
              </button>
              {#if img.caption}
                <div class="caption">{img.caption}</div>
              {/if}
              {@render meta(img)}
            </div>
          {/each}
        </div>
        {#if filteredImages.length === 0}
          <div class="empty-filter-state">No images match this filter.</div>
        {/if}
        {#if visibleCounts.images < filteredImages.length}
          <div class="pagination-row">
            <span>Showing {visibleMediaItems.images.length} of {filteredImages.length}</span>
            <button type="button" class="load-more-button" onclick={() => showMore("images")}>Load more</button>
          </div>
        {/if}
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
          {#each visibleMediaItems.videos as vid}
            <div class="gallery-item">
              <div class="media-label">{vid.key}</div>
              <video controls src={getFilePath(vid)} preload="metadata">
                <track kind="captions" />
              </video>
              {@render meta(vid)}
            </div>
          {/each}
        </div>
        {#if visibleCounts.videos < mediaItems.videos.length}
          <div class="pagination-row">
            <span>Showing {visibleMediaItems.videos.length} of {mediaItems.videos.length}</span>
            <button type="button" class="load-more-button" onclick={() => showMore("videos")}>Load more</button>
          </div>
        {/if}
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
          {#each visibleMediaItems.audios as aud}
            <div class="gallery-item audio-gallery-item">
              <div class="media-label">{aud.key}</div>
              <WaveformAudio src={getFilePath(aud)} />
              {@render meta(aud)}
            </div>
          {/each}
        </div>
        {#if visibleCounts.audios < mediaItems.audios.length}
          <div class="pagination-row">
            <span>Showing {visibleMediaItems.audios.length} of {mediaItems.audios.length}</span>
            <button type="button" class="load-more-button" onclick={() => showMore("audios")}>Load more</button>
          </div>
        {/if}
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
        {#each visibleMediaItems.tables as tbl}
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
                          <button
                            class="table-image-frame"
                            type="button"
                            onclick={() => openImage(cell, tbl)}
                            aria-label="Open table image"
                          >
                            <span class="table-image-placeholder">Loading…</span>
                            <img
                              class="table-image"
                              src={getFilePath(cell)}
                              alt={cell.caption || ""}
                              loading="lazy"
                              decoding="async"
                              onload={markImageLoaded}
                              onerror={markImageFailed}
                            />
                          </button>
                        {:else if isImageList(cell)}
                          <div class="table-image-list">
                            {#each cell as img}
                              <button
                                class="table-image-frame"
                                type="button"
                                onclick={() => openImage(img, tbl)}
                                aria-label="Open table image"
                              >
                                <span class="table-image-placeholder">Loading…</span>
                                <img
                                  class="table-image"
                                  src={getFilePath(img)}
                                  alt={img.caption || ""}
                                  loading="lazy"
                                  decoding="async"
                                  onload={markImageLoaded}
                                  onerror={markImageFailed}
                                />
                              </button>
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
        {/each}
        {#if visibleCounts.tables < mediaItems.tables.length}
          <div class="pagination-row">
            <span>Showing {visibleMediaItems.tables.length} of {mediaItems.tables.length}</span>
            <button type="button" class="load-more-button" onclick={() => showMore("tables")}>Load more</button>
          </div>
        {/if}
      </details>
    {/if}
  {/if}
</div>

{#if selectedImage}
  <div class="image-modal-backdrop" role="presentation" onclick={closeImage}>
    <div
      class="image-modal"
      role="dialog"
      aria-modal="true"
      aria-label="Image preview"
      tabindex="-1"
      onclick={(event) => event.stopPropagation()}
      onkeydown={(event) => event.stopPropagation()}
    >
      <button class="image-modal-close" type="button" onclick={closeImage} aria-label="Close image preview">×</button>
      {#if selectedImageList.length > 1}
        <button
          class="image-modal-nav image-modal-prev"
          type="button"
          onclick={showPreviousImage}
          aria-label="Previous image"
        >
          ‹
        </button>
      {/if}
      <div class="modal-image-frame">
        <span class="modal-image-placeholder">Loading image…</span>
        <img
          src={getFilePath(selectedImage)}
          alt={selectedImage.caption || selectedImage.key || "Image preview"}
          decoding="async"
          onload={markImageLoaded}
          onerror={markImageFailed}
        />
      </div>
      {#if selectedImageList.length > 1}
        <button
          class="image-modal-nav image-modal-next"
          type="button"
          onclick={showNextImage}
          aria-label="Next image"
        >
          ›
        </button>
      {/if}
      <div class="image-modal-info">
        {#if selectedImage.key}
          <div class="image-modal-title">{selectedImage.key}</div>
        {/if}
        {#if selectedImage.caption}
          <div class="image-modal-caption">{selectedImage.caption}</div>
        {/if}
        <div class="meta image-modal-meta">
          <span class="run-dot" style:background={runColor(selectedImage)}></span>
          <span class="meta-text">Run: {selectedImage._run}, Step: {selectedImage.step}</span>
          {#if selectedImageIndex !== null && selectedImageList.length > 1}
            <span class="image-modal-count">{selectedImageIndex + 1} / {selectedImageList.length}</span>
          {/if}
        </div>
      </div>
    </div>
  </div>
{/if}

<style>
  .media-page {
    padding: 20px 24px;
    overflow-y: auto;
    flex: 1;
  }
  .section {
    margin: 16px 0;
  }
  .media-toolbar {
    display: flex;
    justify-content: flex-end;
    align-items: center;
    gap: 12px;
    margin-bottom: 12px;
  }
  .media-control {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: var(--text-sm, 12px);
    color: var(--body-text-color-subdued, #6b7280);
  }
  .media-control select {
    height: 30px;
    border: 1px solid var(--border-color-primary, #d1d5db);
    border-radius: var(--radius-sm, 4px);
    background: var(--background-fill-primary, white);
    color: var(--body-text-color, #1f2937);
    font-size: var(--text-sm, 12px);
    padding: 0 28px 0 8px;
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
  .table-image-frame {
    position: relative;
    display: inline-flex;
    width: 120px;
    height: 80px;
    align-items: center;
    justify-content: center;
    overflow: hidden;
    border: 0;
    border-radius: var(--radius-sm, 4px);
    background: var(--background-fill-secondary, #f3f4f6);
    color: var(--body-text-color-subdued, #6b7280);
    cursor: zoom-in;
    font: inherit;
    padding: 0;
    text-decoration: none;
    vertical-align: top;
  }
  .table-image-placeholder {
    position: absolute;
    inset: 0;
    display: grid;
    place-items: center;
    font-size: var(--text-xs, 11px);
  }
  .table-image-frame:global(.image-loaded) .table-image-placeholder {
    display: none;
  }
  .table-image-frame:global(.image-failed) .table-image-placeholder {
    color: var(--error-text-color, #b91c1c);
  }
  .table-image {
    position: relative;
    z-index: 1;
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
  .image-frame {
    position: relative;
    display: block;
    width: 100%;
    aspect-ratio: 4 / 3;
    overflow: hidden;
    border: 0;
    border-radius: var(--radius-sm, 4px);
    background: var(--background-fill-primary, #f3f4f6);
    color: var(--body-text-color-subdued, #6b7280);
    cursor: zoom-in;
    font: inherit;
    padding: 0;
    text-decoration: none;
  }
  .image-placeholder {
    position: absolute;
    inset: 0;
    display: grid;
    place-items: center;
    font-size: var(--text-sm, 12px);
  }
  .image-frame:global(.image-loaded) .image-placeholder {
    display: none;
  }
  .image-frame:global(.image-failed) .image-placeholder {
    color: var(--error-text-color, #b91c1c);
  }
  .image-frame img {
    position: relative;
    z-index: 1;
    width: 100%;
    height: 100%;
    display: block;
    object-fit: contain;
  }
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
  .image-filter {
    margin-bottom: 12px;
    max-width: 320px;
  }
  .image-filter input {
    width: 100%;
    padding: 7px 10px;
    border: 1px solid var(--border-color-primary, #e5e7eb);
    border-radius: var(--input-radius, 8px);
    background: var(--input-background-fill, white);
    color: var(--body-text-color, #1f2937);
    font-family: inherit;
    font-size: 13px;
    outline: none;
    transition: border-color 0.15s, box-shadow 0.15s;
  }
  .image-filter input:focus {
    border-color: var(--input-border-color-focus, #fdba74);
    box-shadow: 0 0 0 2px var(--primary-50, #fff7ed);
  }
  .image-filter input::placeholder {
    color: var(--input-placeholder-color, #9ca3af);
  }
  .empty-filter-state {
    padding: 16px 0;
    color: var(--body-text-color-subdued, #6b7280);
    font-size: var(--text-sm, 12px);
  }
  .image-modal-backdrop {
    position: fixed;
    inset: 0;
    z-index: 1000;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 32px;
    background: rgb(0 0 0 / 75%);
  }
  .image-modal {
    position: relative;
    display: flex;
    max-width: min(92vw, 1200px);
    max-height: 92vh;
    flex-direction: column;
    overflow: hidden;
    border-radius: var(--radius-lg, 8px);
    background: var(--background-fill-primary, white);
    box-shadow: 0 20px 60px rgb(0 0 0 / 35%);
  }
  .image-modal-close {
    position: absolute;
    top: 8px;
    right: 8px;
    z-index: 2;
    width: 32px;
    height: 32px;
    border: 0;
    border-radius: 999px;
    background: rgb(0 0 0 / 55%);
    color: white;
    cursor: pointer;
    font-size: 24px;
    line-height: 1;
  }
  .image-modal-nav {
    position: absolute;
    top: 50%;
    z-index: 2;
    width: 48px;
    height: 48px;
    border: 0;
    border-radius: 999px;
    background: rgb(0 0 0 / 35%);
    color: white;
    cursor: pointer;
    font-size: 40px;
    line-height: 1;
    transform: translateY(-50%);
  }
  .image-modal-nav:hover {
    background: rgb(0 0 0 / 55%);
  }
  .image-modal-prev {
    left: 12px;
  }
  .image-modal-next {
    right: 12px;
  }
  .modal-image-frame {
    position: relative;
    display: grid;
    min-width: min(70vw, 720px);
    min-height: min(65vh, 520px);
    place-items: center;
    overflow: hidden;
    background: var(--background-fill-secondary, #f3f4f6);
    color: var(--body-text-color-subdued, #6b7280);
  }
  .modal-image-placeholder {
    position: absolute;
    inset: 0;
    display: grid;
    place-items: center;
    font-size: var(--text-sm, 12px);
  }
  .modal-image-frame:global(.image-loaded) .modal-image-placeholder {
    display: none;
  }
  .modal-image-frame:global(.image-failed) .modal-image-placeholder {
    color: var(--error-text-color, #b91c1c);
  }
  .modal-image-frame img {
    position: relative;
    z-index: 1;
    max-width: 100%;
    max-height: calc(92vh - 96px);
    object-fit: contain;
  }
  .image-modal-info {
    display: flex;
    flex-direction: column;
    gap: 4px;
    padding: 10px 14px 12px;
    text-align: center;
  }
  .image-modal-title {
    font-size: var(--text-md, 14px);
    font-weight: 600;
    color: var(--body-text-color, #1f2937);
  }
  .image-modal-caption {
    font-size: var(--text-sm, 12px);
    color: var(--body-text-color-subdued, #6b7280);
  }
  .image-modal-meta {
    justify-content: center;
  }
  .image-modal-count {
    margin-left: 8px;
  }
  .table-section {
    margin-bottom: 16px;
    overflow-x: auto;
  }
  .pagination-row {
    display: flex;
    justify-content: center;
    align-items: center;
    gap: 12px;
    margin-top: 12px;
    font-size: var(--text-sm, 12px);
    color: var(--body-text-color-subdued, #6b7280);
  }
  .load-more-button {
    height: 30px;
    border: 1px solid var(--border-color-primary, #d1d5db);
    border-radius: var(--radius-sm, 4px);
    background: var(--background-fill-primary, white);
    color: var(--body-text-color, #1f2937);
    font-size: var(--text-sm, 12px);
    font-weight: 500;
    padding: 0 10px;
    cursor: pointer;
  }
  .load-more-button:hover {
    background: var(--background-fill-secondary, #f9fafb);
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
