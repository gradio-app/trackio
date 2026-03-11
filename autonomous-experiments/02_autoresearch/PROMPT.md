Run a series of autonomous ML experiments using the autoresearch training script (adapted from https://github.com/karpathy/autoresearch). The script trains a small GPT model for a fixed 5-minute wall-clock budget and reports val_bpb (validation bits per byte — lower is better).

The script has Trackio integrated for real-time monitoring and alerting. If the key metrics start behaving badly (loss spike, NaN, stagnation), a Trackio alert fires and the run terminates early to save compute (might be less than 5 minutes). Watch the alerts — they tell you which experiments failed and why.

Run the train_autoresearch.py script using Hugging Face Jobs, using my locally logged in Hugging Face token, like this:

hf jobs uv run \
    --flavor a100-large \
    --timeout 10m \
    --secrets HF_TOKEN \
    --with 'torch>=2.9' \
    --with 'kernels>=0.11.7' \
    --with pyarrow \
    --with rustbpe \
    --with tiktoken \
    --with trackio \
    --with requests \
    train_autoresearch.py

The first run should be the baseline — run it as-is without modifications.

After the baseline, start experimenting: modify hyperparameters (learning rates, batch size, weight decay, depth, etc.) or architecture choices in the HYPERPARAMETERS section of the script. Edit the file, then submit a new HF Job for each experiment.

For each experiment:
1. Edit train_autoresearch.py (only the HYPERPARAMETERS section or model architecture)
2. Submit the job with a descriptive --run-name (e.g. `--run-name "depth-12"`)
3. Check the output for val_bpb or early termination alerts
4. If val_bpb improved (lower), keep the change. If not, revert.

Key metrics to watch in the output:
- `val_bpb:` — the main metric (lower is better)
- `TERMINATED EARLY` — means Trackio detected bad metrics and killed the run
- Trackio alerts print to stdout so you'll see them in the job logs
