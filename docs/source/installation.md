# Installation

You can install Trackio either from PyPI or from source:

## PyPI

Install the library with pip or [uv](https://docs.astral.sh/uv/):

<hfoptions id="package_manager">
<hfoption id="uv">

uv is a fast Rust-based Python package and project manager. Refer to [Installation](https://docs.astral.sh/uv/getting-started/installation/) for installation instructions.

```bash
uv pip install carbonteq-trackio
```

</hfoption>
<hfoption id="pip">

```bash
pip install carbonteq-trackio
```

</hfoption>
</hfoptions>

## Source

You can also install the latest version from source. First clone the repo and then run the installation with `pip`:

```bash
git clone https://github.com/carbonteq-ai/trackio.git
cd trackio/
```

<hfoptions id="package_manager">
<hfoption id="uv">

```sh
uv pip install .
```

</hfoption>
<hfoption id="pip">

```sh
pip install .
```

</hfoption>
</hfoptions>

If you want the development install you can replace the pip install with the following:

<hfoptions id="package_manager">
<hfoption id="uv">

```sh
uv pip install -e .
```

</hfoption>
<hfoption id="pip">

```sh
pip install -e .
```

</hfoption>
</hfoptions>

## Optional Dependencies

Trackio has optional dependencies for additional features:

**GPU Monitoring (NVIDIA)** - For logging NVIDIA GPU metrics (utilization, memory, temperature, etc.):

```bash
pip install carbonteq-trackio[gpu]
```

**System Monitoring (Apple Silicon)** - For logging CPU, memory, and system metrics on Apple M-series Macs:

```bash
pip install carbonteq-trackio[apple-gpu]
```

**TensorBoard Import** - For importing TensorBoard event files:

```bash
pip install carbonteq-trackio[tensorboard]
```
