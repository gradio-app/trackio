"""Stress-test the Traces viewer with a large batched trace run.

Logs N_STEPS training steps, each containing TRACES_PER_STEP traces, to give
the trace viewer a realistic large batched workload (e.g. an RL training loop
where each step rolls out a batch of samples).
"""

import random

import trackio

PROJECT_NAME = "trace-perf-large-batch"
N_STEPS = 200
TRACES_PER_STEP = 40

QUESTIONS = [
    "Solve the math problem step by step.",
    "Summarize this passage in one sentence.",
    "Translate the following to French.",
    "Write Python code that does what is asked.",
    "Explain the concept like I'm five.",
    "Critique the assistant's previous answer.",
    "Continue the story with one more paragraph.",
    "Identify the bug in this code.",
]

PROMPTS = [
    "What is the derivative of x^3 + 2x?",
    "Why is the sky blue at noon and red at sunset?",
    "Refactor this loop to use map().",
    "List three pros and cons of unit testing.",
    "Compose a haiku about gradient descent.",
    "Outline the proof of the Pythagorean theorem.",
    "Describe a transformer in two sentences.",
    "Suggest a name for a friendly chatbot.",
]

COMPLETIONS = [
    "The derivative is 3x^2 + 2.",
    "Rayleigh scattering: shorter wavelengths scatter more in the atmosphere.",
    "Use [fn(x) for x in items] or list(map(fn, items)).",
    "Pros: confidence, regression catch, design pressure. Cons: maintenance, false sense of security, slow when over-mocked.",
    "Slopes descend slowly, / Learning rate kisses the loss, / Minima nearby.",
    "Construct squares on each side; show areas a^2 + b^2 = c^2 by rearrangement.",
    "A transformer is a sequence model built from self-attention layers and feed-forward blocks.",
    "Call it Trax — it tracks the conversation and stays out of the way.",
]

if __name__ == "__main__":
    print(
        f"Logging {N_STEPS} steps x {TRACES_PER_STEP} traces "
        f"= {N_STEPS * TRACES_PER_STEP} total traces..."
    )

    run = trackio.init(project=PROJECT_NAME, name="rollout-batch")

    for step in range(N_STEPS):
        loss = max(0.01, 2.5 * (0.985**step) + random.uniform(-0.05, 0.05))
        reward = min(1.0, 0.1 + step / N_STEPS + random.uniform(-0.05, 0.05))

        rollouts = []
        for trace_idx in range(TRACES_PER_STEP):
            question = QUESTIONS[trace_idx % len(QUESTIONS)]
            prompt = PROMPTS[trace_idx % len(PROMPTS)]
            completion = COMPLETIONS[trace_idx % len(COMPLETIONS)]
            rollouts.append(
                trackio.Trace(
                    messages=[
                        {"role": "system", "content": question},
                        {"role": "user", "content": prompt},
                        {
                            "role": "assistant",
                            "content": (
                                f"[step {step} | sample {trace_idx}] {completion}"
                            ),
                        },
                    ],
                    metadata={
                        "sample_index": trace_idx,
                        "reward": round(random.uniform(0.0, 1.0), 4),
                        "tokens": random.randint(40, 220),
                    },
                )
            )

        trackio.log(
            {"loss": loss, "reward": reward, "rollouts": rollouts},
            step=step,
        )

        if step % 20 == 0:
            print(f"  step {step}/{N_STEPS}")

    trackio.finish()
    print(f"Done. Open the dashboard and pick project '{PROJECT_NAME}' to view traces.")
