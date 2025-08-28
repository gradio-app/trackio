from mnist import MnistClassifier, batch_size_train, learning_rate, train_loader

import trackio as wandb

n_runs = 3
n_epochs = 3
log_interval = 10

for run in range(n_runs):
    classifier = MnistClassifier()
    wandb.init(
        project="mnist-classifier",
        config={
            "epochs": n_epochs,
            "learning_rate": learning_rate,
            "batch_size": batch_size_train,
        },
    )

    for epoch in range(n_epochs):
        # train
        classifier.start_train()
        for batch_idx, (data, target) in enumerate(train_loader):
            loss = classifier.step_train(data, target)
            if batch_idx % log_interval == 0:
                wandb.log(
                    {
                        "train_percent_complete": 100.0 * batch_idx / len(train_loader),
                        "train_loss": loss,
                    },
                    step=(epoch * len(train_loader)) + batch_idx,
                )

        # test
        test_loss, test_accuracy, test_errors = classifier.test()
        wandb.log(
            {
                "test_loss": test_loss,
                "test_accuracy": test_accuracy,
                "test_errors": wandb.Table(dataframe=test_errors),
            }
        )
