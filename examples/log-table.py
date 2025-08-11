import random

import pandas as pd

import trackio as wandb

EPOCHS = 20
PROJECT_ID = random.randint(100000, 999999)

result_table = None
for run in range(3):
    wandb.init(
        project=f"fake-training-{PROJECT_ID}",
        name=f"test-run-{run}",
        config=dict(
            epochs=EPOCHS,
            learning_rate=0.001,
            batch_size=32,
        ),
    )
    for epoch in range(EPOCHS):
        random_value = random.random()
        
        # update results
        result = {
            "run": run,
            "epoch": epoch,
            "value": random_value,
        }
        if result_table is None:
            result_table = pd.DataFrame([result])
        else:
            result_table = pd.concat([result_table, pd.DataFrame([result])])
        result_table.fillna(0)
        
        # log the result table
        wandb.log(
            {
                "value": random_value,
                "result_table": wandb.Table(dataframe=result_table),
            }
        )