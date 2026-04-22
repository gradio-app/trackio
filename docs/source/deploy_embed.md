# Deploying and Embedding Dashboards

## Deploying to Hugging Face Spaces

When calling [`init`], by default the service will run locally and store project data on the local machine.

But if you pass a `space_id` to [`init`], like:

```py
trackio.init(project="my-project", space_id="orgname/space_id")
```

or

```py
trackio.init(project="my-project", space_id="username/space_id")
```

it will use an existing or automatically deploy a new Hugging Face Space as needed. You should be logged in with the `huggingface-cli` locally and your token should have write permissions to create the Space.

## Syncing Local Projects to Spaces

If you've been logging locally and want to upload your data to a Space after the fact, use `sync`:

```py
trackio.sync(
    project="my-project",
    space_id="username/space_id",
    frontend_dir="./my-trackio-frontend",
)
```

Or from the CLI:

```sh
trackio sync --project "my-project" --space-id "username/space_id" --frontend ./my-trackio-frontend
```

By default, `sync` deploys a **Gradio Space** with a live server. You can also deploy a **static Space** that reads from an HF Bucket (no server needed):

```py
trackio.sync(project="my-project", space_id="username/space_id", sdk="static")
```

```sh
trackio sync --project "my-project" --space-id "username/space_id" --sdk static
```

Static Spaces are lightweight and free — they serve a read-only dashboard backed by Parquet files in an HF Bucket.

## Freezing a Space Snapshot

If you have a live Gradio Space and want to create a read-only static snapshot of a project's data, use `freeze`:

```py
trackio.freeze(
    space_id="username/my-space",
    project="my-project",
    frontend_dir="./my-trackio-frontend",
)
```

Or from the CLI:

```sh
trackio freeze --space-id "username/my-space" --project "my-project" --frontend ./my-trackio-frontend
```

This creates a new static Space (by default named `{space_id}_static`) containing a snapshot of the project's data from the source Space's bucket. The original Space is not modified.

If a custom frontend is configured globally or passed explicitly, Trackio uploads that frontend into the Space so the deployed dashboard uses the same UI.

Note that`freeze()` is a one-time snapshot. If new metrics are later uploaded to the original Gradio Space, the frozen static Space will not update automatically.

You can customize the destination:

```py
trackio.freeze(
    space_id="username/my-space",
    project="my-project",
    new_space_id="username/my-snapshot",
    private=True,
)
```

> **Note:** `freeze()` requires the source to be a Gradio Space with a bucket mounted at `/data`. If the destination Space already exists and is not a Trackio static Space, `freeze()` will refuse to overwrite it.

## Embedding a Trackio Dashboard

One of the reasons we created `trackio` was to make it easy to embed live dashboards on websites, blog posts, or anywhere else you can embed a website.

![image](https://github.com/user-attachments/assets/77f1424b-737b-4f04-b828-a12b2c1af4ef)

If your Trackio dashboard is hosted on Spaces, you can embed it anywhere using an `<iframe>`:

```html
<iframe src="https://username-space_id.hf.space"></iframe>
```

You can also filter the dashboard to display only specific projects or metrics using query parameters. Supported parameters include:

* `project` (string): Show only a specific project.
* `metrics` (comma-separated list): Show only specific metrics, e.g., `train_loss,train_accuracy`.
* `sidebar` (string, `"hidden"` or `"collapsed"`):

  * `"hidden"` hides the sidebar completely.
  * `"collapsed"` keeps the sidebar initially collapsed, but the user can expand it. By default, the sidebar is visible and open.
* `footer` (string, `"false"`): When set to `"false"`, hides the Gradio footer. By default, the footer is visible.
* `xmin` (number): Set the initial minimum value for the x-axis limits across all metrics plots.
* `xmax` (number): Set the initial maximum value for the x-axis limits across all metrics plots.
* `smoothing` (number): Set the initial value of the smoothing slider (0-20, where 0 = no smoothing).
* `accordion` (string, `"hidden"`): When set to `"hidden"`, hides the section header accordions around metric groups. By default, section headers are visible.

You can customize your `<iframe>` using standard attributes such as `width`, `height`, and `style`. For more details, see [MDN Web Docs: `<iframe>`](https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Elements/iframe). For example:

```html
<iframe 
    src="https://trackio-documentation.hf.space/?project=my-project&metrics=train_loss,train_accuracy&sidebar=hidden" 
    width="600" 
    height="630" 
    style="border:0;">
</iframe>
```

<iframe 
    src="https://trackio-documentation.hf.space/?project=my-project&metrics=train_loss,train_accuracy&sidebar=hidden" 
    width="600" 
    height="630" 
    style="border:0;">
</iframe>
