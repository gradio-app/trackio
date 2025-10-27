use serde_json::json;
use trackio::Client;

fn main() {
    // server: export TRACKIO_SHOW_API=1; python -c "import trackio; trackio.init(project='rs-quickstart', embed=False); import time; time.sleep(9999)"
    let client = Client::new()
        .with_base_url(&std::env::var("TRACKIO_SERVER_URL").unwrap_or("http://127.0.0.1:7860".into()))
        .with_project("rs-quickstart")
        .with_run("rs-run-1");

    client.log(json!({"loss": 0.5, "acc": 0.8}), Some(0), None);
    client.log(json!({"loss": 0.4, "acc": 0.82}), Some(1), None);

    client.flush().expect("flush ok");
    println!("flushed. open dashboard to see metrics.");
}