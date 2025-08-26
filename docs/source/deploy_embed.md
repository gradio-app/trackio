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
