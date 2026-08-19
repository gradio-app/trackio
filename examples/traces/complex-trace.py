import random
from datetime import datetime, timedelta, timezone

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
        started = datetime.now(timezone.utc)
        agent_span_id = f"agent_{run_idx}_{step}"
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
                        "label": f"complex-demo-{run_idx}",
                        "environment": "browser",
                        "category": "complex-example",
                        "variant": step,
                        "session_id": f"demo-session-{run_idx}",
                        "status": "success",
                    },
                    spans=[
                        {
                            "id": agent_span_id,
                            "name": "inspect-page",
                            "kind": "span",
                            "start_time": started.isoformat(),
                            "end_time": (started + timedelta(seconds=2.5)).isoformat(),
                            "status": "success",
                        },
                        {
                            "id": f"plan_{run_idx}_{step}",
                            "parent_id": agent_span_id,
                            "name": "provider-request",
                            "kind": "generation",
                            "start_time": started.isoformat(),
                            "end_time": (started + timedelta(seconds=0.8)).isoformat(),
                            "model": "demo-model",
                            "input": {
                                "prompt": "Inspect the page and decide what to do."
                            },
                            "output": {"tool": "extract_title"},
                            "usage": {"input_tokens": 8439, "output_tokens": 188},
                            "cost_usd": 0.0042,
                            "status": "success",
                        },
                        {
                            "id": f"call_{run_idx}_{step}",
                            "parent_id": agent_span_id,
                            "name": "extract_title",
                            "kind": "tool",
                            "start_time": (
                                started + timedelta(seconds=0.9)
                            ).isoformat(),
                            "end_time": (started + timedelta(seconds=1.4)).isoformat(),
                            "input": {"selector": "title"},
                            "output": {"title": f"Trackio Demo {run_idx}-{step}"},
                            "status": "success",
                        },
                        {
                            "id": f"answer_{run_idx}_{step}",
                            "parent_id": agent_span_id,
                            "name": "provider-request",
                            "kind": "generation",
                            "start_time": (
                                started + timedelta(seconds=1.5)
                            ).isoformat(),
                            "end_time": (started + timedelta(seconds=2.5)).isoformat(),
                            "model": "demo-model",
                            "input": {"title": f"Trackio Demo {run_idx}-{step}"},
                            "output": {"answer": f"The page is demo variant {step}."},
                            "usage": {"input_tokens": 1024, "output_tokens": 64},
                            "cost_usd": 0.0008,
                            "status": "success",
                        },
                    ],
                )
            },
            step=step,
        )

    trackio.finish()
