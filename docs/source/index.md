# Trackio

<p align="center">
<img width="75%" src="https://github.com/user-attachments/assets/6d6a41e7-fbc1-43ec-bda6-15f9ff4bd25c" />
</p>

`trackio` is a lightweight, free experiment tracking Python library built on top of Hugging Face Datasets and Spaces 🤗.

![Screen Recording 2025-07-28 at 5 26 32 PM](https://github.com/user-attachments/assets/f3eac49e-d8ee-4fc0-b1ca-aedfc6d6fae1)

- **API compatible** with `wandb.init`, `wandb.log`, and `wandb.finish`. Drop-in replacement: just

  ```python
  import trackio as wandb
  ```

- **Local-first** design: dashboard runs locally by default. You can log to a Hugging Face Space (`space_id`) or to a **self-hosted** Trackio server (`server_url` / `TRACKIO_SERVER_URL`). If both are set, the Space wins.
- Persists logs locally, in a Hugging Face Dataset when using Spaces, or on the machine hosting your self-hosted server
- Visualize experiments with a Gradio dashboard locally, on Hugging Face Spaces, or on your own host when self-hosting
- **LLM-friendly**: Designed for autonomous ML experiments with CLI commands and Python APIs that enable LLMs to easily log and query experiment data.
- Everything here, including hosting on Hugging Face, is **free**!

Trackio is designed to be lightweight (the core codebase is <3,000 lines of Python code), not fully-featured. It is designed in an extensible way and written entirely in Python so that developers can easily fork the repository and add functionality that they care about.
