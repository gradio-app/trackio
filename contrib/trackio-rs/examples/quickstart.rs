// quickstart.rs
use serde_json::json;
use std::{env, thread, time::{Duration, Instant}};

// Trackio Rust client
use trackio::Client;

// Small helpers
fn env_or(name: &str, default: &str) -> String {
    env::var(name).unwrap_or_else(|_| default.to_string())
}

fn wait_for_api(base: &str, ms: u64) -> bool {
    // best-effort ping to /api/projects
    let url = format!("{}/api/projects", base.trim_end_matches('/'));
    let deadline = Instant::now() + Duration::from_millis(ms);
    while Instant::now() < deadline {
        if let Ok(resp) = reqwest::blocking::get(&url) {
            if resp.status().is_success() {
                return true;
            }
        }
        thread::sleep(Duration::from_millis(120));
    }
    false
}

fn main() {
    let base = env_or("TRACKIO_SERVER_URL", "http://127.0.0.1:7860");
    let base = base.trim_end_matches('/').to_string();
    let project = env_or("TRACKIO_PROJECT", "rs-quickstart");
    let run = env_or("TRACKIO_RUN", "rs-run-1");

    println!("* Waiting for Trackio server at: {}", base);
    if !wait_for_api(&base, 5_000) {
        eprintln!("! Trackio API not reachable at {}", base);
        std::process::exit(1);
    }
    println!("* Trackio REST detected at: {}/api/projects", base);

    let client = Client::new()
        .with_base_url(&base)
        .with_project(&project)
        .with_run(&run);

    // Sample points (omit timestamp)
    client.log(json!({"loss": 0.90, "acc": 0.60}), Some(0), None);
    client.log(json!({"loss": 0.75, "acc": 0.68}), Some(1), None);
    client.log(json!({"loss": 0.62, "acc": 0.73}), Some(2), None);

    println!("* Flushing logs...");
    client.flush().expect("flush ok");

    println!("* Done. Open the dashboard:");
    println!(
        "  {}/?selected_project={}&selected_run={}",
        base,
        urlencoding::encode(&project),
        urlencoding::encode(&run)
    );
}