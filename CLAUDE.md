# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Code Style

- AVOID inline comments in code!!!

## Commands

### Development Setup
```bash
# Install with development dependencies
pip install -e .[dev,tensorboard]
```

### Running Tests
```bash
# Run all tests
pytest

# Run specific test file
pytest tests/test_run.py

# Run e2e tests
pytest tests/e2e/
```

### Code Formatting and Linting
```bash
# Format and lint code (required before commits)
ruff check --fix --select I && ruff format
```

### Running the Application
```bash
# Launch dashboard for all projects
trackio show

# Launch dashboard for specific project
trackio show --project "project_name"
```

## Architecture Overview

Trackio is a lightweight experiment tracking library that provides a drop-in replacement for Weights & Biases (wandb). The architecture follows a clean separation between the API layer, UI layer, and storage layer.

### Core Flow
1. **User API** (`trackio/__init__.py`, `run.py`) - Provides wandb-compatible API (`init()`, `log()`, `finish()`)
2. **Storage Layer** (`sqlite_storage.py`) - Manages SQLite database operations for local persistence
3. **UI Layer** (`ui.py`) - Gradio-based web dashboard for visualization
4. **Background Sync** (`commit_scheduler.py`) - Optional Hugging Face dataset synchronization

### Key Design Decisions

**Local-First Architecture**: All data is stored locally in SQLite databases at `~/.cache/huggingface/trackio/`. The system works completely offline by default.

**Queued Logging**: The `Run` class uses a queue-based system for logging to handle concurrent access safely. Background clients process log entries asynchronously.

**Cloud Integration**: Optional deployment to Hugging Face Spaces uses the `deploy.py` module. When deployed, data syncs to HF Datasets every 5 minutes via `CommitScheduler`.

**Context Management**: Uses Python context variables (`context_vars.py`) to track the current run across function calls, similar to wandb's approach.

### Testing Strategy

Tests are split into unit tests (testing individual modules) and e2e tests (testing complete workflows). The `conftest.py` provides fixtures for temporary databases and test isolation. Always run tests before committing changes.

### Important Files for Common Tasks

- **Adding new logging features**: Modify `run.py` (Run class) and `sqlite_storage.py` (storage operations)
- **Changing UI/dashboard**: Edit `ui.py` (Gradio interface)
- **Modifying API compatibility**: Update `trackio/__init__.py` and ensure wandb compatibility
- **Adding import formats**: Extend `imports.py` with new import functions
- **CLI modifications**: Update `cli.py` and entry points in `pyproject.toml`

## Issue Resolution Workflow

When given a GitHub issue to solve, follow this workflow:

1. **Create a new branch** named after the issue (e.g., `fix-issue-123` or descriptive name)
2. **Implement the solution** following the existing code patterns and conventions
3. **Run tests** to ensure nothing is broken: `pytest`
4. **Run linting/formatting**: `ruff check --fix --select I && ruff format`
5. That's it. Never use the `git` commit command after a task is finished.

### Git Commands for Issue Workflow
```bash
git checkout -b fix-issue-NUMBER
```

Always ensure tests pass and code is formatted before pushing.