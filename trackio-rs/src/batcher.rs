use crate::client::Client;
use crate::log_item::LogItem;
use crate::payload::BulkLogPayload;
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::{Duration, Instant};

pub struct Batcher {
    client: Arc<Client>,
    buf: Arc<Mutex<Vec<LogItem>>>,
    max_batch: usize,
    flush_interval: Duration,
}

impl Batcher {
    pub fn new(client: Arc<Client>, max_batch: usize, flush_interval: Duration) -> Self {
        let b = Self {
            client: client.clone(),
            buf: Arc::new(Mutex::new(Vec::new())),
            max_batch,
            flush_interval,
        };

        // background auto-flush thread
        {
            let client_ref = client.clone();
            let buf_ref = b.buf.clone();
            let interval = b.flush_interval;
            thread::spawn(move || loop {
                thread::sleep(interval);
                let _ = Batcher::flush_static(&client_ref, &buf_ref);
            });
        }

        b
    }

    pub fn enqueue(&self, item: LogItem) {
        let mut buf = self.buf.lock().unwrap();
        buf.push(item);
        if buf.len() >= self.max_batch {
            let _ = Batcher::flush_static(&self.client, &self.buf);
        }
    }

    pub fn flush(&self) -> anyhow::Result<()> {
        Self::flush_static(&self.client, &self.buf)
    }

    fn flush_static(client: &Arc<Client>, buf: &Arc<Mutex<Vec<LogItem>>>) -> anyhow::Result<()> {
        let items = {
            let mut guard = buf.lock().unwrap();
            if guard.is_empty() {
                return Ok(());
            }
            let items = guard.clone();
            guard.clear();
            items
        };

        let metrics_list: Vec<_> = items.iter().map(|it| it.metrics.clone()).collect();
        let steps: Vec<_> = items.iter().map(|it| it.step.unwrap_or(-1)).collect();
        let timestamps: Vec<_> = items.iter().map(|it| it.timestamp.clone()).collect();

        let payload = BulkLogPayload {
            project: client.project.clone(),
            run: client.run.clone(),
            metrics_list,
            steps,
            timestamps,
            config: None,
        };

        client.post_json("/api/bulk_log", &payload)?;
        Ok(())
    }
}