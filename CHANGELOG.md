# trackio

## 0.8.0

### Features

- [#331](https://github.com/gradio-app/trackio/pull/331) [`2c02d0f`](https://github.com/gradio-app/trackio/commit/2c02d0fd0a5824160528782402bb0dd4083396d5) - Truncate table string values that are greater than 250 characters (configuirable via env variable).  Thanks @abidlabs!
- [#324](https://github.com/gradio-app/trackio/pull/324) [`50b2122`](https://github.com/gradio-app/trackio/commit/50b2122e7965ac82a72e6cb3b7d048bc10a2a6b1) - Add log y-axis functionality to UI.  Thanks @abidlabs!
- [#326](https://github.com/gradio-app/trackio/pull/326) [`61dc1f4`](https://github.com/gradio-app/trackio/commit/61dc1f40af2f545f8e70395ddf0dbb8aee6b60d5) - Fix: improve table rendering for metrics in Trackio Dashboard.  Thanks @vigneshwaran!
- [#328](https://github.com/gradio-app/trackio/pull/328) [`6857cbb`](https://github.com/gradio-app/trackio/commit/6857cbbe557a59a4642f210ec42566d108294e63) - Support trackio.Table with trackio.Image columns.  Thanks @abidlabs!

## 0.7.0

### Features

- [#277](https://github.com/gradio-app/trackio/pull/277) [`db35601`](https://github.com/gradio-app/trackio/commit/db35601b9c023423c4654c9909b8ab73e58737de) - fix: make grouped runs view reflect live updates.  Thanks @Saba9!
- [#320](https://github.com/gradio-app/trackio/pull/320) [`24ae739`](https://github.com/gradio-app/trackio/commit/24ae73969b09fb3126acd2f91647cdfbf8cf72a1) - Add additional query parms for xmin, xmax, and smoothing.  Thanks @abidlabs!
- [#270](https://github.com/gradio-app/trackio/pull/270) [`cd1dfc3`](https://github.com/gradio-app/trackio/commit/cd1dfc3dc641b4499ac6d4a1b066fa8e2b52c57b) - feature: add support for logging audio.  Thanks @Saba9!

## 0.6.0

### Features

- [#309](https://github.com/gradio-app/trackio/pull/309) [`1df2353`](https://github.com/gradio-app/trackio/commit/1df23534d6c01938c8db9c0f584ffa23e8d6021d) - Add histogram support with wandb-compatible API.  Thanks @abidlabs!
- [#315](https://github.com/gradio-app/trackio/pull/315) [`76ba060`](https://github.com/gradio-app/trackio/commit/76ba06055dc43ca8f03b79f3e72d761949bd19a8) - Add guards to avoid silent fails.  Thanks @Xmaster6y!
- [#313](https://github.com/gradio-app/trackio/pull/313) [`a606b3e`](https://github.com/gradio-app/trackio/commit/a606b3e1c5edf3d4cf9f31bd50605226a5a1c5d0) - No longer prevent certain keys from being used. Instead, dunderify them to prevent collisions with internal usage.  Thanks @abidlabs!
- [#317](https://github.com/gradio-app/trackio/pull/317) [`27370a5`](https://github.com/gradio-app/trackio/commit/27370a595d0dbdf7eebbe7159d2ba778f039da44) - quick fixes for trackio.histogram.  Thanks @abidlabs!
- [#312](https://github.com/gradio-app/trackio/pull/312) [`aa0f3bf`](https://github.com/gradio-app/trackio/commit/aa0f3bf372e7a0dd592a38af699c998363830eeb) - Fix video logging by adding TRACKIO_DIR to allowed_paths.  Thanks @abidlabs!

## 0.5.3

### Features

- [#300](https://github.com/gradio-app/trackio/pull/300) [`5e4cacf`](https://github.com/gradio-app/trackio/commit/5e4cacf2e7ce527b4ce60de3a5bc05d2c02c77fb) - Adds more environment variables to allow customization of Trackio dashboard.  Thanks @abidlabs!

## 0.5.2

### Features

- [#293](https://github.com/gradio-app/trackio/pull/293) [`64afc28`](https://github.com/gradio-app/trackio/commit/64afc28d3ea1dfd821472dc6bf0b8ed35a9b74be) - Ensures that the TRACKIO_DIR environment variable is respected.  Thanks @abidlabs!
- [#287](https://github.com/gradio-app/trackio/pull/287) [`cd3e929`](https://github.com/gradio-app/trackio/commit/cd3e9294320949e6b8b829239069a43d5d7ff4c1) - fix(sqlite): unify .sqlite extension, allow export when DBs exist, clean WAL sidecars on import.  Thanks @vaibhav-research!

### Fixes

- [#291](https://github.com/gradio-app/trackio/pull/291) [`3b5adc3`](https://github.com/gradio-app/trackio/commit/3b5adc3d1f452dbab7a714d235f4974782f93730) - Fix the wheel build.  Thanks @pngwn!

## 0.5.1

### Fixes

- [#278](https://github.com/gradio-app/trackio/pull/278) [`314c054`](https://github.com/gradio-app/trackio/commit/314c05438007ddfea3383e06fd19143e27468e2d) - Fix row orientation of metrics plots.  Thanks @abidlabs!