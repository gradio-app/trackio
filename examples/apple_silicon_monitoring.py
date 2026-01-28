"""
Example: Apple Silicon GPU/System Monitoring

This example demonstrates automatic system metrics logging on Apple Silicon (M-series) Macs.
The library will automatically detect if you're running on Apple Silicon and log:
  - CPU utilization (per core and overall)
  - CPU frequency
  - Memory usage (used, available, total, percent)
  - Swap memory usage
  - Temperature sensors (if available)
  - GPU detection

Requirements:
  pip install trackio[gpu]  # Installs psutil for system monitoring
"""

import time

import trackio

run = trackio.init(
    project="apple-silicon-demo",
    auto_log_gpu=True,
    gpu_log_interval=2.0,
)

for step in range(10):
    trackio.log(
        {
            "loss": 1.0 / (step + 1),
            "accuracy": step * 0.1,
        }
    )

    time.sleep(1)

trackio.finish()

print("\n✓ System metrics have been logged alongside your training metrics!")
print("  View them in the dashboard with: trackio show --project apple-silicon-demo")
