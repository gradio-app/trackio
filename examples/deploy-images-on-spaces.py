import random

import numpy as np
import pandas as pd
from PIL import Image

import trackio

EPOCHS = 20
PROJECT_ID = random.randint(100000, 999999)


trackio.init(
    project=f"deploy-images-on-spaces-{PROJECT_ID}",
    space_id=f"deploy-images-on-spaces-{PROJECT_ID}",
)
image = trackio.Image(
    Image.fromarray(np.random.randint(0, 255, (64, 64, 3), dtype=np.uint8))
)
df = pd.DataFrame({"value": [0.1, 0.2, 0.3], "image": [[image, image], image, image]})
table = trackio.Table(dataframe=df)
trackio.log({"my_table": table})
trackio.finish()
