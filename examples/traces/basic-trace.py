import random

import trackio

PROJECT_ID = random.randint(100000, 999999)
PROJECT_NAME = f"trace-demo-basic-{PROJECT_ID}"

examples = [
    ("What is 2 + 2?", "2 + 2 = 4."),
    ("What is the capital of Australia?", "The capital of Australia is Canberra."),
    (
        "Give me a one-sentence summary of Trackio.",
        "Trackio is a lightweight experiment tracking dashboard for ML and agent workflows.",
    ),
    ("Translate 'hello' to Spanish.", "Hola."),
]

for run_idx in range(2):
    trackio.init(project=PROJECT_NAME, name=f"basic-run-{run_idx}")

    for step, (prompt, completion) in enumerate(examples):
        trackio.log(
            {
                "trace": trackio.Trace(
                    messages=[
                        {"role": "system", "content": "You are a concise assistant."},
                        {"role": "user", "content": prompt},
                        {"role": "assistant", "content": completion},
                    ],
                    metadata={
                        "model_version": f"demo-basic-v{run_idx + 1}",
                        "trace_kind": "basic",
                        "example_index": step,
                    },
                )
            },
            step=step,
        )

    trackio.finish()
