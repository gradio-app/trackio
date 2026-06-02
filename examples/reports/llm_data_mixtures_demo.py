"""
Create a public Trackio Report demo for mock LLM post-training experiments.

Example:

    python examples/reports/llm_data_mixtures_demo.py --deploy

The script creates mock Trackio runs, syncs them to a static dashboard Space,
publishes a nested static report, uploads artifacts to an HF Bucket, and deploys
the report Space.
"""

from __future__ import annotations

import argparse
import json
import random
import shutil
import tempfile
import time
from pathlib import Path

from PIL import Image, ImageDraw

import trackio
from trackio import reports

PROJECT = "llm-data-mixtures-report-demo"
REPORT_SPACE_ID = "abidlabs/trackio-report-demo"
REPORT_BUCKET_ID = "abidlabs/trackio-report-demo-bucket"
DASHBOARD_SPACE_ID = "abidlabs/trackio-report-demo-dashboard"


MIXTURES = [
    {
        "name": "balanced",
        "chat": 35,
        "code": 25,
        "math": 25,
        "safety": 15,
        "mt_bench": 7.4,
        "gsm8k": 64.0,
        "humaneval": 38.2,
        "toxicity": 1.8,
    },
    {
        "name": "code-heavy",
        "chat": 20,
        "code": 50,
        "math": 20,
        "safety": 10,
        "mt_bench": 6.9,
        "gsm8k": 58.5,
        "humaneval": 45.7,
        "toxicity": 2.2,
    },
    {
        "name": "math-heavy",
        "chat": 20,
        "code": 20,
        "math": 50,
        "safety": 10,
        "mt_bench": 6.8,
        "gsm8k": 71.3,
        "humaneval": 34.4,
        "toxicity": 2.4,
    },
    {
        "name": "chat-heavy",
        "chat": 55,
        "code": 15,
        "math": 15,
        "safety": 15,
        "mt_bench": 7.7,
        "gsm8k": 55.8,
        "humaneval": 31.0,
        "toxicity": 1.6,
    },
]


def _draw_bar_chart(path: Path, title: str, values: dict[str, float]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    width, height = 920, 520
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, width - 1, height - 1), outline="#d8dee8")
    draw.text((32, 26), title, fill="#17202c")

    max_value = max(values.values())
    left, top = 70, 90
    bar_height = 54
    gap = 34
    colors = ["#2563eb", "#16a34a", "#dc2626", "#9333ea"]
    for index, (label, value) in enumerate(values.items()):
        y = top + index * (bar_height + gap)
        bar_width = int((width - 260) * value / max_value)
        draw.text((left, y - 22), label, fill="#334155")
        draw.rectangle((left, y, left + bar_width, y + bar_height), fill=colors[index])
        draw.text((left + bar_width + 12, y + 17), f"{value:.1f}", fill="#17202c")
    image.save(path)


def _write_artifacts(workdir: Path, mixture: dict[str, float | str]) -> list[Path]:
    artifact_dir = workdir / "artifacts" / str(mixture["name"])
    artifact_dir.mkdir(parents=True, exist_ok=True)
    metrics = {
        "MT-Bench": float(mixture["mt_bench"]),
        "GSM8K": float(mixture["gsm8k"]),
        "HumanEval": float(mixture["humaneval"]),
        "Safety": 100.0 - float(mixture["toxicity"]),
    }
    chart_path = artifact_dir / "eval_summary.png"
    _draw_bar_chart(chart_path, f"{mixture['name']} evaluation summary", metrics)

    config_path = artifact_dir / "mixture_config.json"
    config_path.write_text(json.dumps(mixture, indent=2) + "\n", encoding="utf-8")

    card_path = artifact_dir / "adapter_card.md"
    card_path.write_text(
        f"""# {mixture["name"]} adapter

Mock LoRA adapter produced for the Trackio Reports demo.

- Chat: {mixture["chat"]}%
- Code: {mixture["code"]}%
- Math: {mixture["math"]}%
- Safety: {mixture["safety"]}%
""",
        encoding="utf-8",
    )
    return [chart_path, config_path, card_path]


def _log_trackio_runs() -> None:
    for mixture in MIXTURES:
        random.seed(str(mixture["name"]))
        trackio.init(
            project=PROJECT,
            name=str(mixture["name"]),
            config={
                "chat_pct": mixture["chat"],
                "code_pct": mixture["code"],
                "math_pct": mixture["math"],
                "safety_pct": mixture["safety"],
                "base_model": "meta-llama/Llama-3.1-8B-Instruct",
                "method": "mock-lora-post-training",
            },
        )
        loss = 2.2
        for step in range(18):
            loss = max(0.55, loss * 0.88 + random.uniform(-0.035, 0.025))
            reward = min(0.82, 0.25 + step * 0.032 + random.uniform(-0.018, 0.018))
            trackio.log(
                {
                    "train/loss": round(loss, 4),
                    "eval/reward": round(reward, 4),
                    "eval/mt_bench": round(float(mixture["mt_bench"]) * step / 17, 4),
                    "eval/gsm8k": round(float(mixture["gsm8k"]) * step / 17, 4),
                    "eval/humaneval": round(
                        float(mixture["humaneval"]) * step / 17, 4
                    ),
                },
                step=step,
            )
            time.sleep(0.02)
        trackio.log(
            {
                "reports/final": trackio.Markdown(
                    f"""# {mixture["name"]} summary

Final mock results:

- MT-Bench: {mixture["mt_bench"]}
- GSM8K: {mixture["gsm8k"]}
- HumanEval: {mixture["humaneval"]}
"""
                )
            }
        )
        trackio.finish()


def _write_report_pages(workdir: Path, dashboard_url: str, deploy: bool) -> None:
    reports.init_report(
        workdir,
        space_id=REPORT_SPACE_ID,
        bucket_id=REPORT_BUCKET_ID,
        force=True,
    )
    experiments_index = workdir / "reports" / "experiments" / "index.md"
    experiments_index.parent.mkdir(parents=True, exist_ok=True)
    experiments_index.write_text(
        """---
title: Experiments
---

# Experiments

This section contains one page per mock data mixture.
""",
        encoding="utf-8",
    )

    overview = workdir / "reports" / "index.md"
    overview.write_text(
        f"""---
title: LLM Data Mixture Report
---

# LLM Data Mixture Report

We post-trained a mock 8B instruction model with four data mixtures and compared
instruction-following, math, code, and safety-oriented proxy metrics.

{{{{ trackio url="{dashboard_url}?project={PROJECT}&sidebar=hidden&footer=false" }}}}

## Takeaways

- The balanced mixture produced the best aggregate tradeoff.
- Code-heavy improved HumanEval but regressed chat quality.
- Math-heavy improved GSM8K and hurt general instruction following.
- Chat-heavy had the best MT-Bench score but weaker code and math transfer.
""",
        encoding="utf-8",
    )

    for mixture in MIXTURES:
        artifacts = _write_artifacts(workdir, mixture)
        notes = f"""Mixture composition:

- Chat: {mixture["chat"]}%
- Code: {mixture["code"]}%
- Math: {mixture["math"]}%
- Safety: {mixture["safety"]}%

Final mock evals: MT-Bench `{mixture["mt_bench"]}`, GSM8K `{mixture["gsm8k"]}`,
HumanEval `{mixture["humaneval"]}`, toxicity `{mixture["toxicity"]}`.

{{{{ trackio url="{dashboard_url}?project={PROJECT}&metrics=train/loss,eval/reward&sidebar=hidden&footer=false" }}}}
"""
        reports.publish_report(
            workdir,
            page=f"reports/experiments/{mixture['name']}.md",
            title=f"{mixture['name']} mixture",
            body=notes,
            artifacts=artifacts,
            upload=deploy,
        )


def _static_space_host(space_id: str) -> str:
    return f"https://{space_id.replace('/', '-')}.static.hf.space"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--deploy", action="store_true")
    parser.add_argument(
        "--workdir",
        type=Path,
        default=None,
        help="Directory for the generated report workspace. Defaults to a temp dir.",
    )
    args = parser.parse_args()

    if args.workdir is None:
        workdir = Path(tempfile.mkdtemp(prefix="trackio-report-demo-"))
    else:
        workdir = args.workdir
        if workdir.exists():
            shutil.rmtree(workdir)
        workdir.mkdir(parents=True)

    _log_trackio_runs()
    dashboard_url = _static_space_host(DASHBOARD_SPACE_ID)
    if args.deploy:
        trackio.sync(project=PROJECT, space_id=DASHBOARD_SPACE_ID, sdk="static")

    _write_report_pages(workdir, dashboard_url, deploy=args.deploy)
    reports.build_report(workdir)

    if args.deploy:
        reports.deploy_report(workdir)

    print(f"Report workspace: {workdir}")
    print(f"Report Space: https://huggingface.co/spaces/{REPORT_SPACE_ID}")
    print(f"Dashboard Space: https://huggingface.co/spaces/{DASHBOARD_SPACE_ID}")
    print(f"Artifact Bucket: https://huggingface.co/buckets/{REPORT_BUCKET_ID}")


if __name__ == "__main__":
    main()
