import numpy as np

import trackio


trackio.init(project="trace-demo-complex")

fake_screenshot = np.random.randint(0, 255, size=(240, 320, 3), dtype=np.uint8)

trackio.log(
    {
        "agent_trace": trackio.Trace(
            messages=[
                {"role": "system", "content": "You are a browser agent."},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Inspect the page and summarize it."},
                        trackio.Image(fake_screenshot, caption="browser screenshot"),
                    ],
                },
                {
                    "role": "assistant",
                    "content": "I will inspect the page and call a tool if needed.",
                    "tool_calls": [
                        {
                            "id": "call_1",
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
                    "content": '{"title": "Trackio Demo"}',
                    "tool_call_id": "call_1",
                },
                {
                    "role": "assistant",
                    "content": "The page appears to be a Trackio demo with a visible screenshot and a simple title.",
                },
            ],
            metadata={"model_version": "agent-preview", "environment": "browser"},
        )
    }
)

trackio.finish()
