import random

import numpy as np

import trackio

PROJECT_ID = random.randint(100000, 999999)
PROJECT_NAME = f"trace-demo-complex-{PROJECT_ID}"


def make_screenshot(seed: int):
    rng = np.random.default_rng(seed)
    return rng.integers(0, 255, size=(240, 320, 3), dtype=np.uint8)


for run_idx in range(2):
    trackio.init(project=PROJECT_NAME, name=f"complex-run-{run_idx}")

    for step in range(4):
        screenshot = make_screenshot(run_idx * 10 + step)
        trackio.log(
            {
                "agent_trace": trackio.Trace(
                    messages=[
                        {"role": "system", "content": "You are a browser agent."},
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "text",
                                    "text": f"Inspect page variant {step} and summarize it.",
                                },
                                trackio.Image(
                                    screenshot,
                                    caption=f"browser screenshot run={run_idx} step={step}",
                                ),
                            ],
                        },
                        {
                            "role": "assistant",
                            "content": "I will inspect the page and call a tool if needed.",
                            "tool_calls": [
                                {
                                    "id": f"call_{run_idx}_{step}",
                                    "type": "function",
                                    "function": {
                                        "name": "extract_title",
                                        "arguments": '{"selector": "title"}',
                                    },
                                }
                            ],
                        },
                        {
                            "role": "tool",
                            "content": f'{{"title": "Trackio Demo {run_idx}-{step}"}}',
                            "tool_call_id": f"call_{run_idx}_{step}",
                        },
                        {
                            "role": "assistant",
                            "content": f"The page variant {step} appears to be a Trackio demo with a visible screenshot and an extracted title.",
                        },
                    ],
                    metadata={
                        "model_version": f"agent-preview-{run_idx}",
                        "environment": "browser",
                        "trace_kind": "complex",
                        "step_variant": step,
                    },
                )
            },
            step=step,
        )

    trackio.finish()
