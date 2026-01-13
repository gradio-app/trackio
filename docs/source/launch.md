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

## Changing the Theme

You can change the theme of the dashboard by providing an optional `theme` argument.

<hfoptions id="language">
<hfoption id="Shell">

```sh
trackio show --theme "soft"
```

</hfoption>
<hfoption id="Python">

```py
import trackio 

trackio.show(theme="soft")
```

</hfoption>
</hfoptions>

To see the available themes, check out the [themes gallery](https://huggingface.co/spaces/gradio/theme-gallery).

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
