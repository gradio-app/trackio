# Manage Projects

## Organizing Your Plots

The dashboard will automatically organize your metrics based on how you name them. It recursively groups metrics according to the `"/"` in their names. For example, if you log the following metrics:

```py
trackio.log({"train/loss": 0.5, "train/accuracy": 0.8, "val/loss": 0.6, "val/accuracy": 0.75})
```

The dashboard will automatically create two groups of plots: `"train"` and `"val"`, each containing the `"loss"` and `"accuracy"` plots.

<iframe 
    src="https://trackio-documentation.hf.space/?project=organize-your-plots&sidebar=hidden" 
    style="width: 100%; border:0;" 
    height="630" 
    style="border:0;">
</iframe>
