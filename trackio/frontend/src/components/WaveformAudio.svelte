<script>
  let { src = "" } = $props();

  const BARS = 72;

  let canvas;
  let audio;
  let peaks = $state([]);
  let duration = $state(0);
  let current = $state(0);
  let playing = $state(false);
  let decodeFailed = $state(false);

  function fmt(t) {
    if (!Number.isFinite(t) || t < 0) return "0:00";
    const m = Math.floor(t / 60);
    const s = Math.floor(t % 60);
    return `${m}:${s.toString().padStart(2, "0")}`;
  }

  async function decode() {
    if (!src) return;
    decodeFailed = false;
    try {
      const res = await fetch(src);
      const buf = await res.arrayBuffer();
      const Ctx = window.AudioContext || window.webkitAudioContext;
      const ctx = new Ctx();
      const audioBuf = await ctx.decodeAudioData(buf);
      duration = audioBuf.duration;
      const data = audioBuf.getChannelData(0);
      const samplesPerBar = Math.max(1, Math.floor(data.length / BARS));
      const out = new Array(BARS);
      for (let i = 0; i < BARS; i++) {
        let sum = 0;
        const start = i * samplesPerBar;
        const end = Math.min(start + samplesPerBar, data.length);
        for (let j = start; j < end; j++) sum += data[j] * data[j];
        out[i] = Math.sqrt(sum / Math.max(1, end - start));
      }
      const max = Math.max(...out, 1e-6);
      peaks = out.map((v) => v / max);
      ctx.close?.();
    } catch {
      decodeFailed = true;
    }
  }

  function draw() {
    if (!canvas || peaks.length === 0) return;
    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    if (rect.width === 0) return;
    canvas.width = rect.width * dpr;
    canvas.height = rect.height * dpr;
    const ctx2 = canvas.getContext("2d");
    ctx2.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx2.clearRect(0, 0, rect.width, rect.height);
    const styles = getComputedStyle(canvas);
    const played = (styles.getPropertyValue("--wave-played") || "#f97316").trim();
    const base = (styles.getPropertyValue("--wave-base") || "#9ca3af").trim();
    const progress = duration > 0 ? current / duration : 0;
    const barW = rect.width / peaks.length;
    const mid = rect.height / 2;
    for (let i = 0; i < peaks.length; i++) {
      const h = Math.max(2, peaks[i] * rect.height * 0.85);
      const frac = (i + 0.5) / peaks.length;
      ctx2.fillStyle = frac < progress ? played : base;
      const w = Math.max(1.5, barW - 2);
      ctx2.fillRect(i * barW + (barW - w) / 2, mid - h / 2, w, h);
    }
  }

  function toggle() {
    if (!audio) return;
    if (audio.paused) {
      audio.play().catch(() => {});
    } else {
      audio.pause();
    }
  }

  function seek(e) {
    if (!audio || !duration) return;
    const rect = canvas.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const t = Math.max(0, Math.min(duration, (x / rect.width) * duration));
    audio.currentTime = t;
    current = t;
  }

  $effect(() => {
    src;
    peaks = [];
    current = 0;
    duration = 0;
    playing = false;
    decode();
  });

  $effect(() => {
    peaks;
    current;
    duration;
    draw();
  });
</script>

<svelte:window onresize={draw} />

<div class="wave-wrap">
  <button
    class="play-btn"
    onclick={toggle}
    aria-label={playing ? "Pause" : "Play"}
    disabled={decodeFailed}
  >
    {#if playing}
      <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
        <rect x="6" y="5" width="4" height="14" rx="1"/>
        <rect x="14" y="5" width="4" height="14" rx="1"/>
      </svg>
    {:else}
      <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
        <path d="M7 5v14l12-7z"/>
      </svg>
    {/if}
  </button>

  <!-- svelte-ignore a11y_click_events_have_key_events -->
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <canvas
    class="wave"
    bind:this={canvas}
    onclick={seek}
  ></canvas>

  <span class="time">{fmt(current)} / {fmt(duration)}</span>

  <audio
    bind:this={audio}
    {src}
    preload="metadata"
    ontimeupdate={() => (current = audio.currentTime)}
    onloadedmetadata={() => (duration = audio.duration)}
    onplay={() => (playing = true)}
    onpause={() => (playing = false)}
    onended={() => {
      playing = false;
      current = 0;
    }}
  >
    <track kind="captions" />
  </audio>
</div>

<style>
  .wave-wrap {
    --wave-base: var(--body-text-color-subdued, #9ca3af);
    --wave-played: var(--color-accent, #f97316);
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 8px 10px;
    background: var(--background-fill-secondary, #f9fafb);
    border: 1px solid var(--border-color-primary, #e5e7eb);
    border-radius: var(--radius-lg, 8px);
    color: var(--body-text-color, #1f2937);
  }
  .play-btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 28px;
    height: 28px;
    border-radius: 50%;
    background: var(--color-accent, #f97316);
    color: white;
    border: none;
    cursor: pointer;
    flex-shrink: 0;
    padding: 0;
  }
  .play-btn:disabled {
    opacity: 0.4;
    cursor: not-allowed;
  }
  .play-btn:hover:not(:disabled) {
    filter: brightness(1.1);
  }
  .wave {
    flex: 1;
    height: 32px;
    min-width: 0;
    cursor: pointer;
  }
  .time {
    font-size: 11px;
    color: var(--body-text-color-subdued, #6b7280);
    font-variant-numeric: tabular-nums;
    flex-shrink: 0;
  }
  audio {
    display: none;
  }
</style>
