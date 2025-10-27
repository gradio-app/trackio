use once_cell::sync::OnceCell;
use parking_lot::Mutex;
use reqwest::blocking::Client as Http;
use reqwest::StatusCode;
use serde::Serialize;
use std::env;
use std::time::Duration;

/// A lightweight Trackio REST client for posting metrics to local or remote Trackio dashboards.
#[derive(Debug)]
pub struct Client {
    base_url: String,
    project: String,
    run: String,
    write_token: Option<String>,

    http: Http,
    cached_bulk_path: OnceCell<String>,

    // batching
    buf: Mutex<Vec<LogItem>>,
    max_batch: usize,
    #[allow(dead_code)]
    flush_interval: Duration,
}

#[derive(Debug, Clone, Serialize)]
struct BulkPayload<'a> {
    project: &'a str,
    run: &'a str,
    #[serde(rename = "metrics_list")]
    metrics_list: Vec<serde_json::Value>,
    steps: Vec<i64>,
    timestamps: Vec<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    config: Option<serde_json::Value>,
}

#[derive(Debug, Clone)]
pub struct LogItem {
    pub metrics: serde_json::Value,
    pub step: Option<i64>,
    pub timestamp: Option<String>,
}

impl Client {
    /// Create a new Trackio client using environment variables for configuration.
    ///
    /// Recognized env vars:
    /// - `TRACKIO_SERVER_URL` (default: http://127.0.0.1:7860)
    /// - `TRACKIO_PROJECT`
    /// - `TRACKIO_RUN`
    /// - `TRACKIO_WRITE_TOKEN`
    /// - `TRACKIO_TIMEOUT_MS`
    /// - `TRACKIO_MAX_BATCH`
    /// - `TRACKIO_FLUSH_INTERVAL_MS`
    pub fn new() -> Self {
        let base = env::var("TRACKIO_SERVER_URL").unwrap_or_else(|_| "http://127.0.0.1:7860".into());
        let project = env::var("TRACKIO_PROJECT").unwrap_or_default();
        let run = env::var("TRACKIO_RUN").unwrap_or_default();
        let write_token = env::var("TRACKIO_WRITE_TOKEN").ok();

        let timeout_ms = env::var("TRACKIO_TIMEOUT_MS")
            .ok()
            .and_then(|s| s.parse::<u64>().ok())
            .unwrap_or(5000);

        let max_batch = env::var("TRACKIO_MAX_BATCH")
            .ok()
            .and_then(|s| s.parse::<usize>().ok())
            .unwrap_or(128);

        let flush_interval = env::var("TRACKIO_FLUSH_INTERVAL_MS")
            .ok()
            .and_then(|s| s.parse::<u64>().ok())
            .map(Duration::from_millis)
            .unwrap_or(Duration::from_millis(200));

        Self {
            base_url: base,
            project,
            run,
            write_token,
            http: Http::builder()
                .timeout(Duration::from_millis(timeout_ms))
                .build()
                .expect("failed to build HTTP client"),
            cached_bulk_path: OnceCell::new(),
            buf: Mutex::new(Vec::with_capacity(max_batch)),
            max_batch,
            flush_interval,
        }
    }

    pub fn with_project(mut self, p: &str) -> Self {
        self.project = p.into();
        self
    }

    pub fn with_run(mut self, r: &str) -> Self {
        self.run = r.into();
        self
    }

    pub fn with_base_url(mut self, u: &str) -> Self {
        self.base_url = u.into();
        self
    }

    /// Logs a single metric dictionary into the in-memory buffer.
    /// Auto-flushes when `max_batch` is reached.
    pub fn log(&self, metrics: serde_json::Value, step: Option<i64>, ts: Option<String>) {
        let mut buf = self.buf.lock();
        buf.push(LogItem {
            metrics,
            step,
            timestamp: ts,
        });
        if buf.len() >= self.max_batch {
            drop(buf);
            let _ = self.flush(); // best-effort flush
        }
    }

    /// Flush all buffered metrics to the Trackio server.
    pub fn flush(&self) -> Result<(), TrackioError> {
        let items = {
            let mut buf = self.buf.lock();
            if buf.is_empty() {
                return Ok(());
            }
            let out = buf.clone();
            buf.clear();
            out
        };

        let mut metrics_list = Vec::with_capacity(items.len());
        let mut steps = Vec::with_capacity(items.len());
        let mut timestamps = Vec::with_capacity(items.len());

        for it in items {
            metrics_list.push(it.metrics);
            steps.push(it.step.unwrap_or(-1));
            timestamps.push(it.timestamp.unwrap_or_else(|| "".into()));
        }

        let payload = BulkPayload {
            project: &self.project,
            run: &self.run,
            metrics_list,
            steps,
            timestamps,
            config: None,
        };

        // Discover a working bulk endpoint once.
        let path = self.cached_bulk_path.get_or_try_init(|| {
            if self.try_post("/api/bulk_log", &payload).is_ok() {
                return Ok("/api/bulk_log".to_string());
            }
            if self.try_post("/gradio_api/bulk_log", &payload).is_ok() {
                return Ok("/gradio_api/bulk_log".to_string());
            }
            Err(TrackioError::NoBulkEndpoint)
        })?;

        self.try_post(path, &payload)
    }

    /// Internal helper to send JSON POST and map non-2xx responses.
    fn try_post<P: AsRef<str>, T: Serialize>(
        &self,
        path: P,
        payload: &T,
    ) -> Result<(), TrackioError> {
        let url = format!("{}{}", self.base_url, path.as_ref());
        let mut req = self.http.post(url).json(payload);
        if let Some(tok) = &self.write_token {
            req = req.header("X-Trackio-Write-Token", tok);
        }
        let resp = req.send().map_err(TrackioError::Http)?;
        if !resp.status().is_success() {
            let status = resp.status();
            let body = resp.text().unwrap_or_default();
            if status == StatusCode::NOT_FOUND {
                return Err(TrackioError::NotFound(body));
            }
            return Err(TrackioError::Status(status.as_u16(), body));
        }
        Ok(())
    }

    /// Flush remaining metrics and stop background tasks (if any).
    pub fn close(&self) -> Result<(), TrackioError> {
        self.flush()
    }
}

#[derive(thiserror::Error, Debug)]
pub enum TrackioError {
    #[error("no Trackio bulk endpoint found")]
    NoBulkEndpoint,
    #[error("HTTP error: {0}")]
    Http(#[from] reqwest::Error),
    #[error("404 Not Found: {0}")]
    NotFound(String),
    #[error("HTTP {0}: {1}")]
    Status(u16, String),
}