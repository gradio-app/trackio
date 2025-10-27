// Minimal Trackio JS client (Node 18+: native fetch, AbortController)

const env = (k, def = "") => process.env[k] ?? def;
const envInt = (k, def) => {
  const v = process.env[k];
  if (!v) return def;
  const n = Number(v);
  return Number.isFinite(n) ? n : def;
};

export class TrackioClient {
  constructor(opts = {}) {
    this.baseURL = opts.baseURL ?? env("TRACKIO_SERVER_URL", "http://127.0.0.1:7860");
    this.project = opts.project ?? env("TRACKIO_PROJECT", "");
    this.run = opts.run ?? env("TRACKIO_RUN", "");
    this.writeToken = opts.writeToken ?? process.env.TRACKIO_WRITE_TOKEN ?? undefined;

    this.timeoutMs = opts.timeoutMs ?? envInt("TRACKIO_TIMEOUT_MS", 5000);
    this.maxBatch = opts.maxBatch ?? envInt("TRACKIO_MAX_BATCH", 128);
    this.autoFlushMs = opts.autoFlushMs ?? envInt("TRACKIO_FLUSH_INTERVAL_MS", 0); // 0 = off

    this._buf = [];
    this._cachedBulkPath = null; // "/api/bulk_log" or "/gradio_api/bulk_log"
    this._timer = null;

    if (this.autoFlushMs > 0) {
      this._timer = setInterval(() => {
        // best-effort, fire-and-forget
        this.flush().catch(() => {});
      }, this.autoFlushMs);
      // don't keep Node process alive because of the timer:
      if (this._timer.unref) this._timer.unref();
    }
  }

  withBaseURL(u) { this.baseURL = u; return this; }
  withProject(p) { this.project = p; return this; }
  withRun(r) { this.run = r; return this; }
  withWriteToken(t) { this.writeToken = t; return this; }

  /**
   * Queue a metric log entry.
   * @param {object} metrics - plain JSON object of metrics.
   * @param {number|null} [step] - optional step (int). If omitted, we send -1 placeholder.
   * @param {string|null} [timestamp] - optional RFC3339 or "" (server accepts "").
   */
  log(metrics, step = null, timestamp = null) {
    this._buf.push({
      metrics: metrics ?? {},
      step: Number.isInteger(step) ? step : -1,
      timestamp: typeof timestamp === "string" ? timestamp : ""
    });
    if (this._buf.length >= this.maxBatch) {
      // best-effort
      this.flush().catch(() => {});
    }
  }

  /**
   * Flush buffered logs to server.
   * Auto-discovers working endpoint on first flush, then caches it.
   */
  async flush() {
    if (this._buf.length === 0) return;

    // swap buffer
    const items = this._buf;
    this._buf = [];

    const payload = {
      project: this.project,
      run: this.run,
      metrics_list: items.map(it => it.metrics),
      steps: items.map(it => it.step ?? -1),
      timestamps: items.map(it => it.timestamp ?? "")
      // config: undefined // can be added once needed
    };

    // discover once
    if (!this._cachedBulkPath) {
      const okApi = await this._tryPost("/api/bulk_log", payload).then(() => true).catch(() => false);
      if (okApi) {
        this._cachedBulkPath = "/api/bulk_log";
      } else {
        const okGradio = await this._tryPost("/gradio_api/bulk_log", payload).then(() => true).catch(() => false);
        if (okGradio) {
          this._cachedBulkPath = "/gradio_api/bulk_log";
        } else {
          throw new Error("trackio: unable to POST to either /api/bulk_log or /gradio_api/bulk_log");
        }
      }
      return; // the two discovery posts already sent the payload
    }

    // normal path
    await this._tryPost(this._cachedBulkPath, payload);
  }

  /**
   * Close the client: clears autoflush timer and flushes anything pending.
   */
  async close() {
    if (this._timer) {
      clearInterval(this._timer);
      this._timer = null;
    }
    await this.flush().catch(() => {});
  }

  async _tryPost(path, payload) {
    const url = this.baseURL.replace(/\/+$/, "") + path;
    const controller = new AbortController();
    const id = setTimeout(() => controller.abort(), this.timeoutMs);

    const headers = { "Content-Type": "application/json" };
    if (this.writeToken) headers["X-Trackio-Write-Token"] = this.writeToken;

    let res;
    try {
      res = await fetch(url, {
        method: "POST",
        headers,
        body: JSON.stringify(payload),
        signal: controller.signal
      });
    } catch (e) {
      clearTimeout(id);
      throw e;
    }
    clearTimeout(id);

    if (!res.ok) {
      const text = await res.text().catch(() => "");
      const msg = `POST ${path} -> ${res.status} ${res.statusText}; body: ${text}`;
      throw new Error(msg);
    }
  }
}