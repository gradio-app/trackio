import pandas as pd
import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim
import torchvision

import trackio as wandb

n_log_test_examples = 20
n_runs = 3
n_epochs = 3
batch_size_train = 64
batch_size_test = 1000
learning_rate = 0.01
momentum = 0.5
log_interval = 10

random_seed = 1
torch.backends.cudnn.enabled = False
torch.manual_seed(random_seed)

train_loader = torch.utils.data.DataLoader(
    torchvision.datasets.MNIST(
        "~/.cache/torchvision-mnist/",
        train=True,
        download=True,
        transform=torchvision.transforms.Compose(
            [
                torchvision.transforms.ToTensor(),
                torchvision.transforms.Normalize((0.1307,), (0.3081,)),
            ]
        ),
    ),
    batch_size=batch_size_train,
    shuffle=True,
)

test_loader = torch.utils.data.DataLoader(
    torchvision.datasets.MNIST(
        "~/.cache/torchvision-mnist/",
        train=False,
        download=True,
        transform=torchvision.transforms.Compose(
            [
                torchvision.transforms.ToTensor(),
                torchvision.transforms.Normalize((0.1307,), (0.3081,)),
            ]
        ),
    ),
    batch_size=batch_size_test,
    shuffle=True,
)


# Build the network
class _Net(nn.Module):
    def __init__(self):
        super(_Net, self).__init__()
        self.conv1 = nn.Conv2d(1, 10, kernel_size=5)
        self.conv2 = nn.Conv2d(10, 20, kernel_size=5)
        self.conv2_drop = nn.Dropout2d()
        self.fc1 = nn.Linear(320, 50)
        self.fc2 = nn.Linear(50, 10)

    def forward(self, x):
        x = F.relu(F.max_pool2d(self.conv1(x), 2))
        x = F.relu(F.max_pool2d(self.conv2_drop(self.conv2(x)), 2))
        x = x.view(-1, 320)
        x = F.relu(self.fc1(x))
        x = F.dropout(x, training=self.training)
        x = self.fc2(x)
        return F.log_softmax(x)


class MnistClassifier:
    def __init__(self):
        self.network = _Net()
        self.optimizer = optim.SGD(
            self.network.parameters(), lr=learning_rate, momentum=momentum
        )

    def start_train(self):
        self.network.train()

    def step_train(self, data, target):
        self.optimizer.zero_grad()
        output = self.network(data)
        loss = F.nll_loss(output, target)
        loss.backward()
        self.optimizer.step()
        return loss.item()

    def test(self):
        self.network.eval()
        test_loss = 0
        correct = 0
        preds = []
        targets = []
        with torch.no_grad():
            for batch_idx, (data, target) in enumerate(test_loader):
                output = self.network(data)
                test_loss += F.nll_loss(output, target, size_average=False).item()
                pred = output.data.max(1, keepdim=True)[1]
                correct += pred.eq(target.data.view_as(pred)).sum()
                if batch_idx % log_interval == 0:
                    for p in pred.numpy().tolist():
                        preds.append(p[0])
                    for t in target.data.numpy().tolist():
                        targets.append(t)
        test_loss /= len(test_loader.dataset)
        test_accuracy = float((100.0 * correct) / len(test_loader.dataset))
        targets = targets[:n_log_test_examples]
        preds = preds[:n_log_test_examples]
        test_results = pd.DataFrame({"target": targets, "prediction": preds})
        return (test_loss, test_accuracy, test_results)


for run in range(n_runs):
    classifier = MnistClassifier()
    wandb.init(
        project="mnist-classifier",
        config={"epochs": n_epochs, "learning_rate": 0.001, "batch_size": 64},
    )

    def train(epoch):
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

    def test(epoch):
        test_loss, test_accuracy, test_results = classifier.test()
        wandb.log(
            {
                "test_loss": test_loss,
                "test_accuracy": test_accuracy,
                "test_results": wandb.Table(dataframe=test_results),
            }
        )

    for epoch in range(n_epochs):
        train(epoch)
        test(epoch)
