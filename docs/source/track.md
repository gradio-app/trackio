# Track

## Introduction

Trackio helps you organize your experiments within a **project**.
A project is a collection of **runs**, where each run represents a single execution of your code with a specific set of parameters and results.

## Initialization

To start tracking an experiment with Trackio, you first need to initialize a project with the [`init`] function:

```python
import trackio

trackio.init(project="my_project")
```

* If the project already exists, it will be loaded.
* If not, Trackio will create a new one.

In both cases, a new run is started automatically, ready for you to log data.

### Naming your run

It's a good idea to give each run a meaningful name for easier organization and later reference.
You can set a name using the `name` parameter:

```python
trackio.init(project="my_project", name="my_first_run")
```

If no name is provided, Trackio generates a default one.

### Grouping runs

You can organize related runs into groups using the `group` parameter. This is particularly useful when you're running multiple experiments with different configurations but want to compare them together:

```python
# Group runs by experiment type
trackio.init(project="my_project", name="baseline_run_1", group="baseline")
trackio.init(project="my_project", name="augmented_run_1", group="augmented")
trackio.init(project="my_project", name="tuned_run_1", group="tuned")
```

Runs with the same group name can be grouped together in sidebar, making it easier to compare related experiments. You can also group runs by any other configuration parameter (see [Tracking Configuration](#tracking-configuration) below).

## Logging Data

Once your run is initialized, you can start logging data using the [`log`] function:

```python
trackio.log({"loss": 0.05})
```

Each call to [`log`] automatically increments the step counter.
If you want to log multiple metrics at once, pass them together:

```python
trackio.log({
    "loss": 0.05,
    "accuracy": 0.95,
})
```

### Logging tables

You can log tabular data using the [`Table`] class. This is useful for tracking results like predictions, or any structured data.

```python
import pandas as pd

df = pd.DataFrame(
    {
        "prompt": ["Trackio", "Logging is"],
        "completion": ["is great!", "easy and fun!"],
        "reward": [0.123, 0.456],
    }
)
trackio.log(
    {
        ...
        "texts": trackio.Table(dataframe=df),
    }
)
```

<iframe 
    src="https://trackio-documentation.hf.space/?project=log-table&metrics=loss,text&sidebar=hidden" 
    width="600" 
    height="630" 
    style="border:0;">
</iframe>

### Logging images

You can log images using the [`Image`] class.

```python
trackio.log({"image": trackio.Image(value="path/to/image.png", caption="Image caption")})
```

Images can be logged from a path, a numpy array, or a PIL Image.

### Logging videos

You can log videos using the [`Video`] class.

```python
import trackio
import numpy as np

# Create a simple video from numpy array
frames = np.random.randint(0, 255, (10, 3, 64, 64), dtype=np.uint8)
video = trackio.Video(frames, caption="Random video", fps=30)
trackio.log({"my_video": video})

# Create a batch of videos
batch_frames = np.random.randint(0, 255, (3, 10, 3, 64, 64), dtype=np.uint8)
batch_video = trackio.Video(batch_frames, caption="Batch of videos", fps=15)
trackio.log({"batch_videos": batch_video})

# Create video from file path
video = trackio.Video("path/to/video.mp4", caption="Video from file")
trackio.log({"file_video": video})
```

Videos can be logged from a file path or a numpy array.

**Numpy array requirements:**
- Must be of type `np.uint8` with RGB values in the range `[0, 255]`
- Shape should be either:
  - `(frames, channels, height, width)` for a single video
  - `(batch, frames, channels, height, width)` for multiple videos (will be tiled into a grid)

## Finishing a Run

When your run is complete, finalize it with [`finish`].
This marks the run as completed and saves all logged data:

```python
trackio.finish()
```

## Resuming a Run

If you need to continue a run (for example, after an interruption), you can resume it by calling [`init`] again with the same project and run name, and setting `resume="must"`:

```python
trackio.init(project="my_project", name="my_first_run", resume="must")
```

This will load the existing run so you can keep logging data.

For more flexibility, use `resume="allow"`. This will resume the run if it exists, or create a new one otherwise.

## Tracking Configuration

You can also track configuration parameters for your runs. This is useful for keeping track of hyperparameters or other settings used in your experiments. You can log configuration data using the `config` parameter in the [`init`] function:

```python
for batch_size in [16, 32, 64]:
    for lr in [0.001, 0.01, 0.1]:
        trackio.init(
            project="hyperparameter_tuning",
            name=f"lr_{lr}_batch_{batch_size}_run",
            config={
                "learning_rate": lr,
                "batch_size": batch_size,
            }
        )
        # ... your training code ...
        trackio.finish()
```

In the dashboard, you can then group by "learning_rate" or "batch_size" to more easily compare runs with different hyperparameters.