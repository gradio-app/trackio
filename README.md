<p align="center">

<img width="75%" src="https://github.com/user-attachments/assets/6d6a41e7-fbc1-43ec-bda6-15f9ff4bd25c" />


</p>

`trackio` is a lightweight, free experiment tracking Python library built on top of 🤗 Datasets and Spaces.


![Screen Recording 2025-07-28 at 5 26 32 PM](https://github.com/user-attachments/assets/f3eac49e-d8ee-4fc0-b1ca-aedfc6d6fae1)


- **API compatible** with `wandb.init`, `wandb.log`, and `wandb.finish` (drop-in replacement: just `import trackio as wandb`)
- *Local-first* design: dashboard runs locally by default. You can also host it on Spaces by specifying a `space_id`.
- Persists logs locally (or in a private Hugging Face Dataset)
- Visualize experiments with a Gradio dashboard locally (or on Hugging Face Spaces)
- Everything here, including hosting on Hugging Faces, is **free**!

Trackio is designed to be lightweight (the core codebase is <1,000 lines of Python code), not fully-featured. It is designed in an extensible way and written entirely in Python so that developers can easily fork the repository and add functionality that they care about.


## Installation

```bash
pip install trackio
```

or with `uv`:

```py
uv pip install trackio
```

## Usage

The usage of `trackio` is designed to be a identical to `wandb` in most cases:

```python
import trackio as wandb
import random
import time

runs = 3
epochs = 8

def simulate_multiple_runs():
    for run in range(runs):
        wandb.init(project="fake-training", config={
            "epochs": epochs,
            "learning_rate": 0.001,
            "batch_size": 64
        })
        
        for epoch in range(epochs):
            train_loss = random.uniform(0.2, 1.0)
            train_acc = random.uniform(0.6, 0.95)
    
            val_loss = train_loss - random.uniform(0.01, 0.1)
            val_acc = train_acc + random.uniform(0.01, 0.05)
    
            wandb.log({
                "epoch": epoch,
                "train_loss": train_loss,
                "train_accuracy": train_acc,
                "val_loss": val_loss,
                "val_accuracy": val_acc
            })
    
            time.sleep(0.2)

    wandb.finish()

simulate_multiple_runs()
```

Running the above will print to the terminal instructions on launching the dashboard.

## Dashboard

You can launch the dashboard by running in your terminal:

```bash
trackio show
```

or, in Python:

```py
import trackio

trackio.show()
```

You can also provide an optional `project` name as the argument to load a specific project directly:

```bash
trackio show --project "my project"
```

or, in Python:

```py
import trackio 

trackio.show(project="my project")
```

## Deploying to Hugging Face Spaces

When calling `trackio.init()`, by default the service will run locally and store project data on the local machine. 

But if you pass a `space_id` to `init`, like:

```py
trackio.init(project="fake-training", space_id="org_name/space_name")
``` 
or 
```py
trackio.init(project="fake-training", space_id="user_name/space_name")
``` 

it will use an existing or automatically deploy a new Hugging Face Space as needed. You should be logged in with the `huggingface-cli` locally and your token should have write permissions to create the Space.

## Embedding a Trackio Dashboard

One of the reasons we created `trackio` was to make it easy to embed live dashboards on websites, blog posts, or anywhere else you can embed a website.

![image](https://github.com/user-attachments/assets/77f1424b-737b-4f04-b828-a12b2c1af4ef)


If you are hosting your Trackio dashboard on Spaces, then you can embed the url of that Space as an IFrame. You can even use query parameters to only specific projects and/or metrics, e.g.

```html
<iframe src="https://abidlabs-trackio-1234.hf.space/?project=fake-training&metrics=train_loss,train_accuracy&sidebar=hidden" width=1600 height=500 frameBorder="0">
```

Supported query parameters:

- `project`: (string) Filter the dashboard to show only a specific project
- `metrics`: (comma-separated list) Filter the dashboard to show only specific metrics, e.g. `train_loss,train_accuracy`
- `sidebar`: (string: one of "hidden" or "collapsed"). If "hidden", then the sidebar will not be visible. If "collapsed", the sidebar will be in a collpased state initially but the user will be able to open it. Otherwise, by default, the sidebar is shown in an open and visible state.

## Examples

To get started and see basic examples of usage, see these files:
* [Basic example of logging metrics locally](https://github.com/gradio-app/trackio/blob/main/examples/fake-training.py)
* [Persisting metrics in a Hugging Face Dataset](https://github.com/gradio-app/trackio/blob/main/examples/persist-dataset.py)
* [Deploying the dashboard to Spaces](https://github.com/gradio-app/trackio/blob/main/examples/deploy-on-spaces.py)

## Note: Trackio is in Beta (DB Schema May Change)

Note that Trackio is in pre-release right now and we may release breaking changes. In particular, the schema of the Trackio sqlite database may change, which may require migrating or deleting existing database files (located by default at: `~/.cache/huggingface/trackio`).  

Since Trackio is in beta, your feedback is welcome! Please create issues with bug reports or feature requests.

## License

MIT License 

## Pronunciation

Trackio is pronounced TRACK-yo, as in "track yo' experiments"
