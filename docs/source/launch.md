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
