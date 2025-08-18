import numpy as np

import trackio
from trackio.sqlite_storage import SQLiteStorage

PROJECT_NAME = "__TRACKIO_TEST_MEDIA_PROJECT__"

def test_image_logging(temp_dir):
		trackio.init(project=PROJECT_NAME, name="test_run")

		image1 = trackio.Image(np.random.randint(255, size=(100, 100, 3), dtype=np.uint8), caption="test_caption1")
		image2 = trackio.Image(np.random.randint(255, size=(100, 100, 3), dtype=np.uint8), caption="test_caption2")
		trackio.log(metrics={"loss": 0.1, "img1": image1})
		trackio.log(metrics={"loss": 0.2, "img1": image1, "img2": image2})
		trackio.finish()

		metrics, images = SQLiteStorage.get_logs(project=PROJECT_NAME, run="test_run")

		assert len(metrics) == 2
		assert len(images) == 2

		assert metrics[0]["loss"] == 0.1
		assert metrics[0]["step"] == 0
		assert metrics[0]["step"] == images[0]["step"]
		assert metrics[0]["timestamp"] == images[0]["timestamp"]
		assert len(images[0]["images"]) == 1
		assert images[0]["images"]["img1"]._to_dict() == image1._to_dict()

		assert metrics[1]["loss"] == 0.2
		assert metrics[1]["timestamp"] == images[1]["timestamp"]
		assert metrics[1]["step"] == images[1]["step"]
		assert len(images[1]["images"]) == 2
		assert images[1]["images"]["img1"]._to_dict() == image1._to_dict()
		assert images[1]["images"]["img2"]._to_dict() == image2._to_dict()
