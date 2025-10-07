# tests/test_audio_smoke.py
import numpy as np

from trackio.media import TrackioAudio as Audio
from trackio.sqlite_storage import SQLiteStorage


def test_audio_array(tmp_path, monkeypatch):
    monkeypatch.setenv("TRACKIO_HOME", str(tmp_path))
    project, run = "audio-proj", "audio-run"
    SQLiteStorage.init_db(project)

    y = np.zeros(16000, dtype=float)  # 1 sec silence @ 16k
    SQLiteStorage.bulk_log(
        project=project,
        run=run,
        metrics_list=[{"clip": Audio(y, sample_rate=16000)}],
        steps=[0],
        timestamps=[""],
    )

    logs = SQLiteStorage.get_logs(project, run)
    payload = logs[0]["clip"]
    assert payload["_type"] == "trackio.audio"
    assert payload["file_path"].endswith(".wav")
