from pathlib import Path

import trackio
from trackio.sqlite_storage import SQLiteStorage


def test_import_from_csv(temp_db):
    trackio.import_csv(
        csv_path=str(Path(__file__).parent / "logs.csv"),
        project="test_project",
        name="test_run",
    )

    results = SQLiteStorage.get_metrics(project="test_project", run="test_run")
    assert len(results) == 4
    assert results[0]["train/loss"] == 12.2
    assert results[0]["train/acc"] == 82.2
    assert results[0]["step"] == 4
    assert results[1]["train/loss"] == 9.5
    assert results[1]["train/acc"] == 93.5
    assert results[1]["step"] == 52
    assert results[2]["train/loss"] == 8.9
    assert results[2]["train/acc"] == 94.9
    assert results[2]["step"] == 72
    assert results[3]["train/loss"] == 8.8
    assert results[3]["train/acc"] == 95.8
    assert results[3]["step"] == 82
    assert "timestamp" in results[0]
    assert "timestamp" in results[1]
    assert "timestamp" in results[2]
    assert "timestamp" in results[3]
