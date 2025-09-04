#!/usr/bin/env python3
"""
Example script demonstrating trackio's support for infinity and NaN values.

This script shows how trackio now handles edge cases like:
- Positive infinity (float('inf'))
- Negative infinity (float('-inf'))
- Not a Number (float('nan'))

These values commonly occur in machine learning scenarios such as:
- Gradient norms that explode
- Loss functions that diverge
- Division by zero in calculations
- Invalid mathematical operations
"""

import trackio


def main():
    print("🚀 Starting infinity and NaN logging example...")

    # Initialize trackio project
    trackio.init(project="infinity_demo", name="infinity_demo_run")

    print("📊 Logging various types of values...")

    # Log normal values
    trackio.log(
        {"epoch": 1, "normal_loss": 0.5, "accuracy": 0.95, "learning_rate": 0.001}
    )

    # Simulate gradient explosion scenario
    trackio.log(
        {
            "epoch": 2,
            "normal_loss": 0.3,
            "accuracy": 0.97,
            "grad_norm": float("inf"),  # Gradient explosion!
            "learning_rate": 0.001,
        }
    )

    # Simulate division by zero scenario
    trackio.log(
        {
            "epoch": 3,
            "loss": float("-inf"),  # Loss went to negative infinity
            "accuracy": 0.98,
            "grad_norm": 2.5,
            "learning_rate": 0.001,
        }
    )

    # Simulate invalid mathematical operation
    trackio.log(
        {
            "epoch": 4,
            "loss": 0.1,
            "accuracy": float("nan"),  # NaN from invalid calculation
            "grad_norm": 1.8,
            "learning_rate": 0.001,
        }
    )

    # Log complex nested structure with infinity values
    trackio.log(
        {
            "epoch": 5,
            "train_metrics": {
                "train": {
                    "loss": 0.05,
                    "accuracy": 0.99,
                    "grad_norm": float("inf"),  # Nested infinity
                },
                "validation": {
                    "loss": float("-inf"),  # Nested negative infinity
                    "accuracy": 0.985,
                    "f1_score": float("nan"),  # Nested NaN
                },
            },
            "hyperparameters": {
                "batch_size": 32,
                "learning_rate": 0.0001,
                "temperature": float("inf"),  # Infinity in hyperparameters
            },
            "edge_cases": [
                1.0,
                float("inf"),
                -5.0,
                float("-inf"),
                float("nan"),
            ],  # List with mixed values
        }
    )

    print("✅ Successfully logged all values including infinities and NaN!")
    print("📈 All values are now stored safely and can be visualized")

    # Finish the run
    trackio.finish()

    print("\n🎯 Example completed successfully!")
    print("💡 The infinity and NaN values have been converted to JSON-safe strings:")
    print("   • float('inf') → 'Infinity'")
    print("   • float('-inf') → '-Infinity'")
    print("   • float('nan') → 'NaN'")
    print("\n📊 Run the dashboard to see the results:")
    print('   trackio show --project "infinity_demo"')


if __name__ == "__main__":
    main()
