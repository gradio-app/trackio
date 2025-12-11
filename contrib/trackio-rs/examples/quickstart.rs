// quickstart.rs
use serde_json::{json, Value};
use std::{env, thread, time::{Duration, Instant}};

fn env_or(name: &str, default: &str) -> String {
    env::var(name).unwrap_or_else(|_| default.to_string())
}

fn post_json(url: &str, body: &Value) -> Result<(u16, String), reqwest::Error> {
    let client = reqwest::blocking::Client::new();
    let r = client.post(url).json(body).send()?;
    let status = r.status().as_u16();
    let text = r.text().unwrap_or_default();
    Ok((status, text))
}

fn main() {
    let base = env_or("TRACKIO_SERVER_URL", "http://127.0.0.1:7860");
    let base = base.trim_end_matches('/').to_string();

    let hf_token = env::var("HF_TOKEN")
        .expect("HF_TOKEN is required (write token for your HF Space)");

    // Trackio bulk_log schema: project, run, metrics, step, config
    let logs = json!([
        {
            "project": "rs-quickstart",
            "run": "rs-run-1",
            "metrics": { "loss": 0.90, "acc": 0.60 },
            "step": 0,
            "config": Value::Null
        },
        {
            "project": "rs-quickstart",
            "run": "rs-run-1",
            "metrics": { "loss": 0.75, "acc": 0.68 },
            "step": 1,
            "config": Value::Null
        },
        {
            "project": "rs-quickstart",
            "run": "rs-run-1",
            "metrics": { "loss": 0.62, "acc": 0.73 },
            "step": 2,
            "config": Value::Null
        }
    ]);

    // Body format: { "data": [ logs, HF_TOKEN ] }
    let body = json!({
        "data": [ logs, hf_token ]
    });

    let url = format!("{}/gradio_api/call/bulk_log", base);
    println!("* POST {}", url);

    let (status, text) = post_json(&url, &body).expect("POST request failed");

    println!("status: {}", status);
    println!("{}", text);

    println!(
        "Open dashboard:\n  {}/?selected_project=rs-quickstart&selected_run=rs-run-1",
        base
    );
}