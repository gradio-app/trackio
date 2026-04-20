from trl import GRPOConfig, GRPOTrainer

import trackio


trackio.init(project="trace-demo-trl")


def log_rollouts(prompts, completions, rewards, step, model_version):
    trackio.log(
        {
            "traces": [
                trackio.Trace(
                    messages=[
                        {"role": "user", "content": prompt},
                        {"role": "assistant", "content": completion},
                    ],
                    metadata={
                        "reward": float(reward),
                        "step": step,
                        "model_version": model_version,
                    },
                )
                for prompt, completion, reward in zip(prompts, completions, rewards)
            ]
        },
        step=step,
    )


trainer = GRPOTrainer(
    model="Qwen/Qwen2.5-0.5B",
    reward_funcs=[],
    args=GRPOConfig(output_dir="out", report_to="trackio"),
    train_dataset=[],
)

# Wire `log_rollouts(...)` into your callback or reward loop.
# trainer.train()
