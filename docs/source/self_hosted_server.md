# Self-host the Trackio server

You can run the Trackio dashboard and API on your own machine (or any host you control) and send metrics from training scripts to that server over HTTP. This is an alternative to logging to a Hugging Face Space via `space_id`.

## Run the server locally

Install Trackio, then start the dashboard. By default it listens on `127.0.0.1` and uses the port from `GRADIO_SERVER_PORT` if set, otherwise **7860** (see [Launch the Dashboard](launch.md)).

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

Leave that process running while you train. The terminal prints a base URL for the UI and a URL that includes a **write token**; anyone who can reach that URL with the token can perform write operations supported by the server (for example renaming runs), so treat it like a secret on untrusted networks.

## Listen on all interfaces

To access the dashboard from another machine on your network (or from containers), bind to all interfaces:

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

Ensure your firewall and security policies allow the traffic you intend.

## Point training code at your server

In your training script, pass the **full base URL** of the running server (including `http://` or `https://`). You can also set the environment variable `TRACKIO_SERVER_URL` instead of passing an argument.

```py
import trackio

trackio.init(project="my-project", server_url="http://127.0.0.1:7860/")
trackio.log({"loss": 0.25})
trackio.finish()
```

`server_url` is mutually exclusive with `space_id`. Hugging Face–specific options such as `dataset_id` and `bucket_id` are not used together with `server_url`; configure persistence on the machine where the server runs (for example via `TRACKIO_DIR` on that host). See [Environment Variables](environment_variables.md).

## Related

- [Launch the Dashboard](launch.md) — CLI options, port, and remote access
- [Environment Variables](environment_variables.md) — `TRACKIO_SERVER_URL`, `TRACKIO_DIR`, and others
