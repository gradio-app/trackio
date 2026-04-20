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

import torch
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
    {"prompt": "What is 2 + 2?", "reference_completion": "2 + 2 = 4."},
    {
        "prompt": "What color is the sky on a clear day?",
        "reference_completion": "The sky is typically blue on a clear day.",
    },
    {
        "prompt": "Translate 'good morning' to French.",
        "reference_completion": "Bonjour.",
    },
    {
        "prompt": "Name the capital of Japan.",
        "reference_completion": "Tokyo is the capital of Japan.",
    },
    {
        "prompt": "Give one use of Trackio.",
        "reference_completion": "Trackio can be used to inspect training logs and traces.",
    },
]


def format_example(example):
    return {
        "text": (
            "### Instruction:\n"
            f"{example['prompt']}\n\n"
            "### Response:\n"
            f"{example['reference_completion']}"
        )
    }


dataset = Dataset.from_list([format_example(example) for example in examples * 2])


class TraceLoggingCallback(TrainerCallback):
    def __init__(self, prompt_examples, run_label, tokenizer):
        self.prompt_examples = prompt_examples
        self.run_label = run_label
        self.tokenizer = tokenizer

    def _generate_completion(self, model, prompt):
        encoded = self.tokenizer(
            prompt,
            return_tensors="pt",
            truncation=True,
            max_length=64,
        )
        encoded = {key: value.to(model.device) for key, value in encoded.items()}

        was_training = model.training
        model.eval()
        with torch.no_grad():
            generated = model.generate(
                **encoded,
                max_new_tokens=24,
                do_sample=False,
                pad_token_id=self.tokenizer.pad_token_id,
                eos_token_id=self.tokenizer.eos_token_id,
            )
        if was_training:
            model.train()

        prompt_length = encoded["input_ids"].shape[1]
        completion_ids = generated[0][prompt_length:]
        completion = self.tokenizer.decode(completion_ids, skip_special_tokens=True)
        completion = completion.strip()
        return completion or "(empty generation)"

    def on_log(self, args, state, control, logs=None, **kwargs):
        if not logs or state.global_step <= 0:
            return

        model = kwargs.get("model")
        if model is None:
            return

        sample = self.prompt_examples[
            (state.global_step - 1) % len(self.prompt_examples)
        ]
        trackio.log(
            {
                "trace": trackio.Trace(
                    messages=[
                        {
                            "role": "system",
                            "content": "You are a supervised fine-tuning demo model.",
                        },
                        {"role": "user", "content": sample["prompt"]},
                        {
                            "role": "assistant",
                            "content": self._generate_completion(
                                model, sample["prompt"]
                            ),
                        },
                    ],
                    metadata={
                        "label": self.run_label,
                        "trainer": "trl-sft",
                        "loss": float(logs.get("loss", 0.0)),
                        "global_step": int(state.global_step),
                        "reference_completion": sample["reference_completion"],
                    },
                )
            },
            step=int(state.global_step),
        )


for run_idx in range(2):
    run_name = f"trl-run-{run_idx}"
    model = AutoModelForCausalLM.from_pretrained(MODEL_NAME)

    trainer = SFTTrainer(
        model=model,
        args=SFTConfig(
            output_dir=f"./trl_trace_output_{PROJECT_ID}_{run_idx}",
            per_device_train_batch_size=2,
            max_steps=5,
            logging_steps=1,
            save_strategy="no",
            report_to="trackio",
            project=PROJECT_NAME,
            run_name=run_name,
            trackio_space_id=None,
            learning_rate=5e-5,
            dataset_text_field="text",
            max_length=64,
        ),
        train_dataset=dataset,
        processing_class=tokenizer,
        callbacks=[TraceLoggingCallback(examples, run_name, tokenizer)],
    )

    trainer.train()
