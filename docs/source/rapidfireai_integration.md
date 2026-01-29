# RapidFire AI Integration

[RapidFire AI](https://github.com/RapidFireAI/rapidfireai) enables rapid experimentation for easier, faster, and more impactful AI customization. It is built for agentic RAG, context engineering, fine-tuning, and post-training of LLMs and other DL models, delivering 16-24x higher throughput without extra resources. It supports two key use cases:

- **Fine-tuning and post-training**: Compare learning rates, LoRA configurations, batch sizes, and other training hyperparameters
- **RAG optimization**: Evaluate chunking strategies, embedding models, retrieval approaches, and reranking settings

When running experiments, you often have many configurations executing simultaneously. RapidFire AI provides native Trackio integration to track and visualize all of these runs with minimal setup.

## Installation

Trackio is included as a dependency of RapidFire AI:

```bash
pip install rapidfireai
```

## Configuration

Enable Trackio as the tracking backend by setting environment variables before importing RapidFire components:

```python
import os

# Enable Trackio as the tracking backend
os.environ["RF_TRACKIO_ENABLED"] = "true"

# Optionally disable other tracking backends for standalone Trackio usage
os.environ["RF_MLFLOW_ENABLED"] = "false"
os.environ["RF_TENSORBOARD_ENABLED"] = "false"
```

You can also set the Trackio project name:

```sh
export TRACKIO_PROJECT_NAME="my-experiment"
```

## Fine-Tuning Example

For complete working examples, see the tutorial notebooks:
- [SFT with Trackio Tutorial](https://github.com/RapidFireAI/rapidfireai/blob/main/tutorial_notebooks/fine-tuning/trackio/rf-tutorial-sft-trackio.ipynb)
- [SFT with Trackio Tutorial (Colab Version)](https://github.com/RapidFireAI/rapidfireai/blob/main/tutorial_notebooks/fine-tuning/trackio/rf-colab-tutorial-sft-trackio.ipynb)

Here's a minimal example of running a fine-tuning experiment with Trackio tracking:

```python
import os
os.environ["RF_TRACKIO_ENABLED"] = "true"

from rapidfireai import Experiment
from rapidfireai.automl import RFGridSearch, RFModelConfig, RFLoraConfig, RFSFTConfig

experiment = Experiment(experiment_name="my-sft-experiment", mode="fit")

config = RFModelConfig(
    model_name="TinyLlama/TinyLlama-1.1B-Chat-v1.0",
    peft_config=RFLoraConfig(r=8, lora_alpha=16, target_modules=["q_proj", "v_proj"]),
    training_args=RFSFTConfig(
        learning_rate=1e-4,
        max_steps=128,
        logging_steps=2,
        eval_strategy="steps",
        eval_steps=4,
    ),
    model_type="causal_lm",
)

experiment.run_fit(
    RFGridSearch(configs=[config], trainer_type="SFT"),
    create_model_fn,
    train_dataset,
    eval_dataset,
    num_chunks=4
)
```

## RAG Optimization Example

For complete working examples, see the tutorial notebooks:
- [RAG FiQA with Trackio Tutorial](https://github.com/RapidFireAI/rapidfireai/blob/main/tutorial_notebooks/rag-contexteng/trackio/rf-tutorial-rag-fiqa-trackio.ipynb)
- [RAG FiQA with Trackio Tutorial (Colab Version)](https://github.com/RapidFireAI/rapidfireai/blob/main/tutorial_notebooks/rag-contexteng/trackio/rf-colab-tutorial-rag-fiqa-trackio.ipynb)

RapidFire AI also supports RAG pipeline optimization. Enable Trackio tracking the same way:

```python
import os
os.environ["RF_TRACKIO_ENABLED"] = "true"

from rapidfireai import Experiment
from rapidfireai.evals.automl import List, RFGridSearch, RFLangChainRagSpec, RFvLLMModelConfig

experiment = Experiment(experiment_name="my-rag-experiment", mode="evals")

rag_spec = RFLangChainRagSpec(
    document_loader=your_document_loader,
    text_splitter=your_text_splitter,
    embedding_cls=your_embedding_class,
    search_kwargs={"k": List([5, 10])},  # 2 retrieval configs to compare
)

config_group = RFGridSearch({
    "vllm_config": RFvLLMModelConfig(rag=rag_spec, ...),
    "batch_size": 32,
    ...
})

experiment.run_evals(
    config_group=config_group,
    dataset=eval_dataset,
    num_actors=1,
    num_shards=4,
)
```

## What Gets Tracked

RapidFire AI automatically logs the following to Trackio:

**Fine-Tuning Metrics**:
- `loss`, `learning_rate`, `epoch`, `step` - Training progress
- `eval_loss` - Validation loss
- Custom metrics from your `compute_metrics` function (e.g., `rougeL`, `bleu`)

**RAG Evaluation Metrics**:
- Retrieval metrics: `Precision`, `Recall`, `F1 Score`, `NDCG@K`, `MRR`
- Generation metrics: Custom metrics you define (e.g., `Accuracy`)

**Run Configuration**:
- All hyperparameters for each run
- Model settings, LoRA configurations, chunking strategies, etc.

## Viewing the Dashboard

Launch the Trackio dashboard to visualize your experiments:

```bash
trackio show --project "my-sft-experiment"
```

Or from Python:

```python
import trackio
trackio.show(project="my-sft-experiment")
```

The dashboard displays real-time training curves for all your runs, making it easy to compare configurations side-by-side:

![Trackio dashboard showing RapidFire AI fine-tuning metrics](./trackio-screenshot-sft.png)

*Trackio dashboard comparing 4 fine-tuning runs with different hyperparameters. The plots show training loss, validation loss, learning rate schedules, and ROUGE-L scores—making it easy to identify which configuration (Run 4, in orange) achieves the lowest loss and best generation quality.*

**Documentation**:
- [RapidFire AI Documentation](https://oss-docs.rapidfire.ai/) - Getting started guide
- [RapidFire AI GitHub](https://github.com/RapidFireAI/rapidfireai) - Source code and tutorials
