# /// script
# dependencies = [
#   "trackio",
#   "trl",
#   "datasets",
#   "transformers",
#   "torch",
# ]
# ///

import random

from datasets import Dataset
from transformers import AutoModelForCausalLM, AutoTokenizer, TrainerCallback
from trl import SFTConfig, SFTTrainer

import trackio

PROJECT_ID = random.randint(100000, 999999)
PROJECT_NAME = f"trace-demo-trl-{PROJECT_ID}"
MODEL_NAME = "sshleifer/tiny-gpt2"

tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
if tokenizer.pad_token is None:
    tokenizer.pad_token = tokenizer.eos_token

examples = [
    {"prompt": "What is 2 + 2?", "completion": "2 + 2 = 4."},
    {
        "prompt": "What color is the sky on a clear day?",
        "completion": "The sky is typically blue on a clear day.",
    },
    {"prompt": "Translate 'good morning' to French.", "completion": "Bonjour."},
    {
        "prompt": "Name the capital of Japan.",
        "completion": "Tokyo is the capital of Japan.",
    },
    {
        "prompt": "Give one use of Trackio.",
        "completion": "Trackio can be used to inspect training logs and traces.",
    },
]


def format_example(example):
    return {
        "text": (
            "### Instruction:\n"
            f"{example['prompt']}\n\n"
            "### Response:\n"
            f"{example['completion']}"
        )
    }


dataset = Dataset.from_list([format_example(example) for example in examples * 2])


class TraceLoggingCallback(TrainerCallback):
    def __init__(self, prompt_examples, run_label):
        self.prompt_examples = prompt_examples
        self.run_label = run_label

    def on_log(self, args, state, control, logs=None, **kwargs):
        if not logs or state.global_step <= 0:
            return

        sample = self.prompt_examples[
            (state.global_step - 1) % len(self.prompt_examples)
        ]
        reward = max(0.0, 1.0 - float(logs.get("loss", 0.0)))
        trackio.log(
            {
                "trace": trackio.Trace(
                    messages=[
                        {
                            "role": "system",
                            "content": "You are a supervised fine-tuning demo model.",
                        },
                        {"role": "user", "content": sample["prompt"]},
                        {"role": "assistant", "content": sample["completion"]},
                    ],
                    metadata={
                        "model_version": self.run_label,
                        "trainer": "trl-sft",
                        "loss": float(logs.get("loss", 0.0)),
                        "reward": reward,
                        "global_step": int(state.global_step),
                    },
                )
            },
            step=int(state.global_step),
        )


for run_idx in range(2):
    run_name = f"trl-run-{run_idx}"
    trackio.init(project=PROJECT_NAME, name=run_name)

    model = AutoModelForCausalLM.from_pretrained(MODEL_NAME)

    trainer = SFTTrainer(
        model=model,
        args=SFTConfig(
            output_dir=f"./trl_trace_output_{PROJECT_ID}_{run_idx}",
            per_device_train_batch_size=2,
            max_steps=5,
            logging_steps=1,
            save_strategy="no",
            report_to="none",
            learning_rate=5e-5,
            dataset_text_field="text",
            max_length=64,
        ),
        train_dataset=dataset,
        processing_class=tokenizer,
        callbacks=[TraceLoggingCallback(examples, run_name)],
    )

    trainer.train()
    trackio.finish()
