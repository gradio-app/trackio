// src/client.ts

export interface TrackioOptions {
  baseURL?: string;
  project?: string;
  run?: string;
  writeToken?: string;
  timeoutMs?: number;
  maxBatch?: number;
  autoFlushMs?: number;
}

interface LogEntry {
  metrics: Record<string, any>;
  step: number;
  timestamp: string;
}

const env = (k: string, def: string = ""): string => process.env[k] ?? def;

const envInt = (k: string, def: number): number => {
  const v = process.env[k];
  if (!v) return def;
  const n = Number(v);
  return Number.isFinite(n) ? n : def;
};

export class TrackioClient {
  private baseURL: string;
  private project: string;
  private run: string;
  private writeToken?: string;
  private timeoutMs: number;
  private maxBatch: number;
  private autoFlushMs: number;
  
  private _buf: LogEntry[] = [];
  private _cachedBulkPath: string | null = null;
  private _timer: NodeJS.Timeout | null = null;

  constructor(opts: TrackioOptions = {}) {
    this.baseURL = opts.baseURL ?? env("TRACKIO_SERVER_URL", "http://127.0.0.1:7860");
    this.project = opts.project ?? env("TRACKIO_PROJECT", "");
    this.run = opts.run ?? env("TRACKIO_RUN", "");
    this.writeToken = opts.writeToken ?? process.env.TRACKIO_WRITE_TOKEN;

    this.timeoutMs = opts.timeoutMs ?? envInt("TRACKIO_TIMEOUT_MS", 5000);
    this.maxBatch = opts.maxBatch ?? envInt("TRACKIO_MAX_BATCH", 128);
    this.autoFlushMs = opts.autoFlushMs ?? envInt("TRACKIO_FLUSH_INTERVAL_MS", 0);

    if (this.autoFlushMs > 0) {
      this._timer = setInterval(() => {
        this.flush().catch(() => {});
      }, this.autoFlushMs);
      if (this._timer && (this._timer as any).unref) (this._timer as any).unref();
    }
  }

  // Helper static method for EB-1A "Ease of Use" argument
  static fromEnv(): TrackioClient {
    return new TrackioClient();
  }

  withBaseURL(u: string): this { this.baseURL = u; return this; }
  withProject(p: string): this { this.project = p; return this; }
  withRun(r: string): this { this.run = r; return this; }
  withWriteToken(t: string): this { this.writeToken = t; return this; }

  log(metrics: Record<string, any>, step: number | null = null, timestamp: string | null = null): void {
    this._buf.push({
      metrics: metrics ?? {},
      step: Number.isInteger(step) ? (step as number) : -1,
      timestamp: typeof timestamp === "string" ? timestamp : ""
    });
    
    if (this._buf.length >= this.maxBatch) {
      this.flush().catch(() => {});
    }
  }

  async flush(): Promise<void> {
    if (this._buf.length === 0) return;

    const items = [...this._buf];
    this._buf = [];

    const payload = {
      project: this.project,
      run: this.run,
      metrics_list: items.map(it => it.metrics),
      steps: items.map(it => it.step),
      timestamps: items.map(it => it.timestamp)
    };

    if (!this._cachedBulkPath) {
      const okApi = await this._tryPost("/api/bulk_log", payload).then(() => true).catch(() => false);
      if (okApi) {
        this._cachedBulkPath = "/api/bulk_log";
      } else {
        const okGradio = await this._tryPost("/gradio_api/bulk_log", payload).then(() => true).catch(() => false);
        if (okGradio) {
          this._cachedBulkPath = "/gradio_api/bulk_log";
        } else {
          throw new Error("trackio: unable to POST to either endpoint");
        }
      }
      return;
    }

    await this._tryPost(this._cachedBulkPath, payload);
  }

  async close(): Promise<void> {
    if (this._timer) {
      clearInterval(this._timer);
      this._timer = null;
    }
    await this.flush().catch(() => {});
  }

  private async _tryPost(path: string, payload: any): Promise<void> {
    const url = this.baseURL.replace(/\/+$/, "") + path;
    const controller = new AbortController();
    const id = setTimeout(() => controller.abort(), this.timeoutMs);

    const headers: Record<string, string> = { "Content-Type": "application/json" };
    if (this.writeToken) headers["X-Trackio-Write-Token"] = this.writeToken;

    try {
      const res = await fetch(url, {
        method: "POST",
        headers,
        body: JSON.stringify(payload),
        signal: controller.signal
      });

      if (!res.ok) {
        const text = await res.text().catch(() => "");
        throw new Error(`POST ${path} -> ${res.status} ${res.statusText}; body: ${text}`);
      }
    } finally {
      clearTimeout(id);
    }
  }
}