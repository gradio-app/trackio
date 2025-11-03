# Migrating to Trackio

It's easy to migrate to Trackio from other experiment tracking libraries with minimal code changes. This guide shows you how to migrate from popular experiment tracking tools.

## Weights & Biases (`wandb`)

Migrating from Weights & Biases to Trackio is extremely easy because **Trackio uses the exact same API syntax as wandb**. In most cases, you only need to change the import statement!

### Simple Migration

The most basic migration requires just changing your import:

```diff
- import wandb
+ import trackio as wandb

# The rest of your code stays exactly the same!
wandb.init(project="my-project")
wandb.log({"loss": 0.5, "accuracy": 0.8})
wandb.finish()
```

### Complete Example

Here's a more comprehensive example showing that all wandb functionality works with Trackio:

```diff
- import wandb
+ import trackio as wandb
import numpy as np

# Initialize run - same API
wandb.init(
    project="image-classification",
    name="experiment-1",
    config={
        "learning_rate": 0.01,
        "batch_size": 32,
        "epochs": 10
    }
)

# Log metrics - same API
for epoch in range(10):
    loss = np.random.random()
    accuracy = np.random.random()
    
    wandb.log({
        "epoch": epoch,
        "loss": loss,
        "accuracy": accuracy,
        "learning_rate": wandb.config.learning_rate
    })

# Log images - same API
wandb.log({"sample_image": wandb.Image("path/to/image.jpg")})

# Finish run - same API
wandb.finish()
```

### Advanced Features

Trackio supports rich data logging with Tables and Images - same API as wandb:

```diff
- import wandb
+ import trackio as wandb
import numpy as np

wandb.init(project="data-analysis")

# Log images - same API
image_array = np.random.randint(0, 255, (100, 100, 3), dtype=np.uint8)
wandb.log({
    "sample_image": wandb.Image(image_array, caption="Generated sample"),
    "model_diagram": wandb.Image("architecture.png")
})

# Log tables - same API
columns = ["epoch", "train_loss", "val_loss", "accuracy"]
data = [
    [1, 0.8, 0.6, 0.75],
    [2, 0.6, 0.5, 0.82],
    [3, 0.4, 0.45, 0.89]
]
table = wandb.Table(data=data, columns=columns)
wandb.log({"training_results": table})

wandb.finish()
```


## Neptune

Migrating from Neptune requires a few more changes since Neptune has a different API structure, but the migration is still straightforward.

### Basic Logging Migration

```diff
- import neptune

+ import trackio

# Neptune initialization
- run = neptune.init_run(
-     project="my-workspace/my-project",
-     api_token="your-token"
- )

# Trackio initialization
+ trackio.init(project="my-project")

# Neptune logging
- run["parameters"] = {"learning_rate": 0.01, "batch_size": 32}
- run["metrics/loss"].log(0.5)
- run["metrics/accuracy"].log(0.8)

# Trackio logging
+ trackio.config.update({"learning_rate": 0.01, "batch_size": 32})
+ trackio.log({"loss": 0.5, "accuracy": 0.8})

# Neptune finish
- run.stop()

# Trackio finish
+ trackio.finish()
```

### Complete Training Loop Migration

```diff
- import neptune
+ import trackio
import numpy as np

# Neptune setup
- run = neptune.init_run(
-     project="my-workspace/classification-project",
-     name="experiment-1",
-     tags=["pytorch", "cnn"]
- )

# Trackio setup
+ trackio.init(
+     project="classification-project",
+     name="experiment-1",
+     tags=["pytorch", "cnn"]
+ )

# Configuration
config = {"learning_rate": 0.01, "epochs": 10, "batch_size": 32}

- run["parameters"] = config
+ trackio.config.update(config)

# Training loop
for epoch in range(config["epochs"]):
    # Simulate training
    train_loss = np.random.random()
    val_accuracy = np.random.random()
    
    # Neptune logging
-     run["metrics/train/loss"].log(train_loss)
-     run["metrics/val/accuracy"].log(val_accuracy)
-     run["metrics/epoch"].log(epoch)

    # Trackio logging
+     trackio.log({
+         "train/loss": train_loss,
+         "val/accuracy": val_accuracy,
+         "epoch": epoch
+     })

# File uploads
- run["model/weights"].upload("model.pth")
+ trackio.save("model.pth")

# Cleanup
- run.stop()
+ trackio.finish()
```

### Key Migration Points

1. **Initialization**: Replace `neptune.init_run()` with `trackio.init()`
2. **Logging**: Use `trackio.log()` with dictionaries instead of individual metric assignments
3. **Cleanup**: Replace `run.stop()` with `trackio.finish()`

## Benefits to Migrating

- **Simpler API**: Flat dictionary logging vs nested attribute access
- **Local development**: Work offline by default
- **Free hosting**: Deploy dashboards on Hugging Face Spaces at no cost
- **Familiar interface**: If you've used `wandb` before in particular, the API is unchanged