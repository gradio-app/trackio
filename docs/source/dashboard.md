
# Dashboard

You can launch the dashboard by running in your terminal:

<hfoptions id="language">
<hfoption id="bash">

```bash
trackio show
```

</hfoption>
<hfoption id="Python">

```py
import trackio

trackio.show()
```

</hfoption>
</hfoptions>

You can also provide an optional `project` name as the argument to load a specific project directly:

<hfoptions id="language">
<hfoption id="bash">

```bash
trackio show --project "my-project"
```

</hfoption>
<hfoption id="Python">

```py
import trackio 

trackio.show(project="my-project")
```

</hfoption>
</hfoptions>

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

## Embedding a Trackio Dashboard

One of the reasons we created `trackio` was to make it easy to embed live dashboards on websites, blog posts, or anywhere else you can embed a website.

![image](https://github.com/user-attachments/assets/77f1424b-737b-4f04-b828-a12b2c1af4ef)

If you are hosting your Trackio dashboard on Spaces, then you can embed the url of that Space as an IFrame. You can even use query parameters to only specific projects and/or metrics, e.g.

```html
<iframe src="https://abidlabs-trackio-1234.hf.space/?project=my-project&metrics=train_loss,train_accuracy&sidebar=hidden" width=1600 height=500 frameBorder="0">
```

Supported query parameters:

- `project`: (string) Filter the dashboard to show only a specific project
- `metrics`: (comma-separated list) Filter the dashboard to show only specific metrics, e.g. `train_loss,train_accuracy`
- `sidebar`: (string: one of "hidden" or "collapsed"). If "hidden", then the sidebar will not be visible. If "collapsed", the sidebar will be in a collpased state initially but the user will be able to open it. Otherwise, by default, the sidebar is shown in an open and visible state.

## Organizing Your Plots

The dashboard will automatically organize your metrics based on how you name them. It recursively groups metrics according to the `"/"` in their names. For example, if you log the following metrics:

```py
trackio.log({"train/loss": 0.5, "train/accuracy": 0.8, "val/loss": 0.6, "val/accuracy": 0.75})
```

The dashboard will automatically create two groups of plots: `"train"` and `"val"`, each containing the `"loss"` and `"accuracy"` plots.

<iframe src="https://trackio-documentation.hf.space/?project=organize-your-plots" width=600 height=600 frameBorder="0"></iframe>  
