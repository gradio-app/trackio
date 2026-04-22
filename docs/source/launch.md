# Launching the Dashboard

## Launching a Local Dashboard

You can launch the dashboard by running:

<hfoptions id="language">
<hfoption id="Shell">

```sh
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

## Loading a Specific Project

You can also provide an optional `project` name as the argument to load a specific project directly:

<hfoptions id="language">
<hfoption id="Shell">

```sh
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

## Using a Custom Frontend

You can replace the bundled dashboard with your own static frontend directory. The directory only needs an `index.html` file; your frontend can call the existing Trackio API under `/api/*`.

<hfoptions id="language">
<hfoption id="Shell">

```sh
trackio show --frontend ./my-trackio-frontend
```

</hfoption>
<hfoption id="Python">

```py
import trackio 

trackio.show(frontend_dir="./my-trackio-frontend")
```

</hfoption>
</hfoptions>

If the provided frontend directory is missing or invalid, Trackio falls back to a shipped starter template.

## Setting a Persistent Default Frontend

If you want the same custom frontend to be used by `trackio show`, `trackio sync`, and deploy flows by default, save it in Trackio's persistent config:

```sh
trackio config set frontend ./my-trackio-frontend
```

Reset it with:

```sh
trackio config unset frontend
```

## Customizing Plot Colors

You can customize the color palette used for plot lines by providing a `color_palette` argument. This is useful if you want to match your organization's branding or have specific color preferences.

<hfoptions id="language">
<hfoption id="Shell">

```sh
trackio show --color-palette "#FF0000,#00FF00,#0000FF"
```

</hfoption>
<hfoption id="Python">

```py
import trackio 

trackio.show(color_palette=["#FF0000", "#00FF00", "#0000FF"])
```

</hfoption>
</hfoptions>

The colors will be cycled through when displaying multiple runs. You can provide as many or as few colors as you like.

## Enabling Remote Access

By default, the dashboard binds to `127.0.0.1` (localhost), which means it can only be accessed from the same machine. To allow remote access from other machines on the network, use the `--host` option:

<hfoptions id="language">
<hfoption id="Shell">

```sh
trackio show --host 0.0.0.0
```

</hfoption>
<hfoption id="Python">

```py
import trackio 

trackio.show(host="0.0.0.0")
```

</hfoption>
</hfoptions>

This is particularly useful when running Trackio on a remote server or in a containerized environment where you need to access the dashboard from a different machine.

## Launching a Dashboard in Jupyter Notebooks

You can also launch the dashboard directly within a Jupyter Notebook. Just use the same command as above:

```py
import trackio

trackio.show()
```

Check the [demo notebook](https://github.com/gradio-app/trackio/blob/main/examples/notebook_integration.ipynb).
