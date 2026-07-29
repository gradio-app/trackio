import io
import math
import random

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import plotly.express as px
import plotly.graph_objects as go
from matplotlib.animation import FuncAnimation

import trackio as wandb

EPOCHS = 6


def plotly_figure(losses):
    return px.line(x=list(range(len(losses))), y=losses, title="Loss (plotly express)")


def plotly_graph_objects_figure(losses, accuracies):
    fig = go.Figure()
    fig.add_trace(go.Scatter(y=losses, name="loss", mode="lines+markers"))
    fig.add_trace(go.Scatter(y=accuracies, name="accuracy", mode="lines+markers"))
    fig.update_layout(title="Loss vs. accuracy (plotly graph_objects)")
    return fig


def matplotlib_figure(losses):
    fig, ax = plt.subplots()
    ax.plot(losses, marker="o")
    ax.set_title("Loss (matplotlib figure)")
    ax.set_xlabel("epoch")
    return fig


def matplotlib_animation():
    fig, ax = plt.subplots()
    ax.set_xlim(0, 2 * math.pi)
    ax.set_ylim(-1.1, 1.1)
    (line,) = ax.plot([], [])

    xs = [i * 2 * math.pi / 50 for i in range(51)]

    def update(frame):
        line.set_data(xs[:frame], [math.sin(x + frame / 5) for x in xs[:frame]])
        return (line,)

    return FuncAnimation(fig, update, frames=len(xs), blit=True)


def custom_html(epoch, loss, accuracy):
    return f"""
    <h2>Epoch {epoch}</h2>
    <table border="1" cellpadding="6" style="border-collapse:collapse">
        <tr><th>metric</th><th>value</th></tr>
        <tr><td>loss</td><td>{loss:.4f}</td></tr>
        <tr><td>accuracy</td><td>{accuracy:.4f}</td></tr>
    </table>
    <p><em>Rendered from a raw HTML fragment.</em></p>
    """


def main():
    project_name = f"html-logging-demo-{random.randint(10000, 99999)}"
    wandb.init(project=project_name, name="html-run")

    losses, accuracies = [], []

    for epoch in range(EPOCHS):
        loss = 2.0 * math.exp(-epoch / 3.0) + random.uniform(-0.05, 0.05)
        accuracy = 1.0 - loss / 3.0
        losses.append(loss)
        accuracies.append(accuracy)

        mpl_fig = matplotlib_figure(losses)

        plt.figure()
        plt.plot(accuracies, color="green")
        plt.title("Accuracy (pyplot module)")

        wandb.log(
            {
                "loss": loss,
                "accuracy": accuracy,
                "plotly_express": plotly_figure(losses),
                "plotly_graph_objects": plotly_graph_objects_figure(losses, accuracies),
                "matplotlib_figure": mpl_fig,
                "pyplot_module": plt,
                "custom_html": wandb.Html(
                    custom_html(epoch, loss, accuracy), caption=f"epoch {epoch}"
                ),
            },
            step=epoch,
        )

        plt.close("all")

    anim = matplotlib_animation()
    html_file = io.StringIO(
        "<!doctype html><html><body>"
        "<h2>From a file-like object</h2>"
        "<p>This document was passed to <code>trackio.Html</code> as a stream.</p>"
        "</body></html>"
    )

    wandb.log(
        {
            "matplotlib_animation": wandb.Html(anim, caption="sine wave animation"),
            "html_from_stream": wandb.Html(html_file),
            "full_document": wandb.Html(
                "<!doctype html><html><head><style>"
                "body{background:#111;color:#eee;font-family:monospace}"
                "</style></head><body><h2>Full document</h2>"
                "<p>Not wrapped by trackio, so these styles apply.</p>"
                "</body></html>",
                caption="full html document",
            ),
            "no_inject": wandb.Html(
                "<h2>inject=False</h2><p>Logged as a bare fragment.</p>",
                inject=False,
                caption="fragment without wrapping",
            ),
        },
        step=EPOCHS,
    )

    plt.close("all")
    wandb.finish()


if __name__ == "__main__":
    main()
