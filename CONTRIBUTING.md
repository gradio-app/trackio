# Contributing to Trackio

The best way to help Trackio today is by **opening a detailed issue** rather than a pull request.

## The best way to contribute: open a great issue

We have **paused accepting pull requests from outside the Trackio maintainer team.** As AI coding agents have become widespread, the volume of community PRs has grown to the point where reviewing them carefully takes more maintainer time than the alternative: pointing our own coding agents at a well-described issue and solving it ourselves.

So the single most valuable thing you can do is **file a clear, detailed, reproducible issue.** A great issue lets us (and our agents) understand and fix the problem quickly, and it helps us prioritize what to work on next for Trackio.

> If you are a member of the Trackio maintainer team, the project structure and development setup sections further down still apply to you.

### Reporting a bug

Please [open an issue](https://github.com/gradio-app/trackio/issues/new) and include:

1. **A clear, descriptive title** that summarizes the problem.
2. **What you expected to happen** vs. **what actually happened.**
3. **Step-by-step instructions to reproduce the bug**, numbered and as specific as possible.
4. **A minimal reproduction.** This is the most important part. Please include the smallest self-contained script that triggers the bug (for example, a few `trackio.init()` / `trackio.log()` calls), and/or a link to a Trackio dashboard on [Hugging Face Spaces](https://huggingface.co/spaces) that shows the issue.
5. **Your environment**: Trackio version (`trackio.__version__`), Python version, operating system, and browser (for dashboard issues).
6. **Screenshots, screen recordings, or error tracebacks** where relevant.

The smaller and more self-contained the reproduction, the faster we can fix it.

### Requesting a feature

Please [open an issue](https://github.com/gradio-app/trackio/issues/new) and include:

1. **A clear, descriptive title.**
2. **The problem or use case** you're trying to solve, and where Trackio falls short today.
3. **A detailed description of the feature** you'd like, including a proposed API or an example of how you imagine it would be used in code.
4. **Alternatives you've considered**, including any workarounds you're currently using.

Trackio is designed to stay lightweight. For non-core functionality, we encourage you to fork the repository and build on it; see [Forking Trackio](README.md#forking-trackio).

## Project Structure

> The following sections are primarily for the Trackio maintainer team. If you're an outside contributor, you're welcome to run Trackio locally to build a clean reproduction for your issue.

- `__init__.py` and `run.py`: the main user-facing API (`init()`, `log()`, `finish()`).
- `sqlite_storage.py`: the SQLite storage backend that persists tracking data.
- `ui/`: the Gradio API server that exposes the dashboard's endpoints. This can run either locally or on Hugging Face Spaces.
- `frontend/`: the Svelte 5 dashboard served alongside the Gradio API.

## Development Setup

1. Clone the repository
2. Install Trackio with development dependencies
   ```bash
   pip install -e ".[dev,tensorboard]"
   ```
3. Run tests:
   ```bash
   python -m pytest
   ```
4. Format your code using Ruff:
   ```bash
   ruff check --fix --select I && ruff format
   ```
5. If you change the dashboard, rebuild it:
   ```bash
   cd trackio/frontend
   npm ci
   npm run build
   ```

Thank you to everyone who has contributed to Trackio!

<p align="center">
  <img src="https://contrib.rocks/image?repo=gradio-app/trackio" />
</p>
