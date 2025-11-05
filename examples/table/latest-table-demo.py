import random

import pandas as pd

import trackio

project_name = f"table-latest-demo-{random.randint(0, 1000000)}"

trackio.init(project=project_name, name="run_a")

for step in range(4):
    data = [{"content": f"Row {i + 1} for Run A"} for i in range(step + 1)]
    df = pd.DataFrame(data)

    trackio.log(
        {
            "my_table": trackio.Table(dataframe=df),
        }
    )


trackio.init(project=project_name, name="run_b")

for step in range(4):
    data = [{"content": f"Row {i + 1} for Run B"} for i in range(step + 1)]
    df = pd.DataFrame(data)

    trackio.log(
        {
            "my_table": trackio.Table(dataframe=df),
        }
    )

trackio.finish()
