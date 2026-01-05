# Installation

You can install Trackio either from PyPI or from source:

## PyPI

Install the library with pip or [uv](https://docs.astral.sh/uv/):

<hfoptions id="package_manager">
<hfoption id="uv">

uv is a fast Rust-based Python package and project manager. Refer to [Installation](https://docs.astral.sh/uv/getting-started/installation/) for installation instructions.

```bash
uv pip install trackio
```

</hfoption>
<hfoption id="pip">

```bash
pip install trackio
```

</hfoption>
</hfoptions>

## Source

You can also install the latest version from source. First clone the repo and then run the installation with `pip`:

```bash
git clone https://github.com/gradio-app/trackio.git
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

**GPU Monitoring** - For logging NVIDIA GPU metrics (utilization, memory, temperature, etc.):

```bash
pip install trackio[gpu]
```

**TensorBoard Import** - For importing TensorBoard event files:

```bash
pip install trackio[tensorboard]
```
