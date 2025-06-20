import random
from pathlib import Path

import trackio

PROJECT_ID = random.randint(100000, 999999)

trackio.import_csv(
    csv_path=str(Path(__file__).parent / "logs.csv"),
    project=f"fake-training-{PROJECT_ID}",
)
