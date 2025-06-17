# Contributing to Trackio

Thank you for your interest in contributing to Trackio! This document provides guidelines and information for contributing to the project.

## Contribution Guidelines

Trackio is designed to be a lightweight and extensible tracking tool. We welcome contributions that:

- Improve or enhance core functionality
- Fix bugs in existing features
- Add essential features that align with the project's goals

For non-core functionality or significant feature additions, we encourage you to fork the repository and build upon it. This helps keep the main project lightweight and focused.

## Project Structure

The project is organized as follows:

- `__init__.py` and `run.py`: These files contain the main user-facing API. They handle API calls to the Gradio interface.
- `ui.py`: Contains the Gradio application that provides the web interface. This can run either locally or on Hugging Face Spaces.
- `sqlite_storage.py`: Implements the SQLite storage backend that persists tracking data.

The flow of data is:

> User API (`__init__.py` or `run.py`) → Gradio UI (`ui.py`) → SQLite Storage (`sqlite_storage.py`)


## Development Setup

1. Fork and clone the repository
2. Install development dependencies
   ```bash
   pip install -r requirements.txt 
   pip install pytest ruff
   ```
3. Run tests before submitting changes:
   ```bash
   python -m pytest
   ```
4. Format your code using Ruff:
   ```bash
   ruff check --fix --select I && ruff format
   ```

## Pull Request Process

1. Ensure your code passes all tests
2. Format your code using Ruff
3. Update documentation if necessary
4. Submit a pull request with a clear description of your changes

Thank you for contributing to Trackio! 