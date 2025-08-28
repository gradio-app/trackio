# Track

## Introduction

Trackio helps you organize your experiments within a **project**.
A project is a collection of **runs**, where each run represents a single execution of your code with a specific set of parameters and results.

## Initialization

To start tracking an experiment with Trackio, you first need to initialize a project with the [`init`] function:

```python
import trackio

trackio.init(project_name="my_project")
```

* If the project already exists, it will be loaded.
* If not, Trackio will create a new one.

In both cases, a new run is started automatically, ready for you to log data.

### Naming your run

It’s a good idea to give each run a meaningful name for easier organization and later reference.
You can set a name using the `run_name` parameter:

```python
trackio.init(project_name="my_project", run_name="my_first_run")
```

If no name is provided, Trackio generates a default one.

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

## Finishing a Run

When your run is complete, finalize it with [`finish`].
This marks the run as completed and saves all logged data:

```python
trackio.finish()
```

## Resuming a Run

If you need to continue a run (for example, after an interruption), you can resume it by calling [`init`] again with the same project and run name, and setting `resume="must"`:

```python
trackio.init(project_name="my_project", run_name="my_first_run", resume="must")
```

This will load the existing run so you can keep logging data.

For more flexibility, use `resume="allow"`. This will resume the run if it exists, or create a new one otherwise.

## Tracking Configuration

You can also track configuration parameters for your runs. This is useful for keeping track of hyperparameters or other settings used in your experiments. You can log configuration data using the `config` parameter in the [`init`] function:

```python
trackio.init(
    project_name="my_project",
    run_name="my_first_run",
    config={
        "learning_rate": 0.001,
        "batch_size": 32,
    }
)
```
