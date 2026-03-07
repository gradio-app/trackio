Run a series of experiments sequentially as an autonomous machine learning researcher. Start with learning rates of 1, then 0.5, then 0.1, and so on. The idea is to find the largest learning rate that doesn't lead to wild oscillations in validation loss. So keep watching the Trackio Alerts. If you see instability, then just terminate the job and lower the learning rate, and keep going until you have stable training.

Run the train_nanogpt.py script using Hugging Face Jobs, using my locally logged in Hugging Face token, like this:

hf jobs uv run \
    --flavor a100-large \
    --timeout 10m \
    --secrets HF_TOKEN \
    --with torch \
    --with numpy \
    train_nanogpt.py
