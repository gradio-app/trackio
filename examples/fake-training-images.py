import math
import random
import time

from PIL import Image as PILImage
from PIL import ImageDraw

import trackio as wandb

EPOCHS = 12
W = H = 128


def lissajous(t, w=W, h=H):
    x = (w // 2) + int((w // 3) * math.sin(2.0 * t))
    y = (h // 2) + int((h // 3) * math.sin(3.0 * t + math.pi / 4))
    return x, y


def render_overlay(target_xy, pred_xy):
    img = PILImage.new("RGB", (W, H), "black")
    draw = ImageDraw.Draw(img)

    tx, ty = target_xy
    draw.ellipse((tx - 5, ty - 5, tx + 5, ty + 5), fill=(0, 255, 0))

    px, py = pred_xy
    draw.ellipse((px - 5, py - 5, px + 5, py + 5), fill=(255, 80, 80))

    draw.line([(tx, ty), (px, py)], fill=(255, 255, 0), width=1)
    return img


def main():
    project_id = random.randint(10000, 99999)
    project_name = f"image-logging-demo-{project_id}"

    for run_index in range(1, 3):
        run_name = f"image-run-{run_index}"
        wandb.init(project=project_name, name=run_name)

        pred_x, pred_y = random.randint(0, W - 1), random.randint(0, H - 1)

        for epoch in range(EPOCHS):
            t = epoch / 3.0
            target = lissajous(t)

            lr = 0.35
            noise_scale = max(0.0, 5.0 * (1.0 - epoch / (EPOCHS - 1)))
            pred_x += lr * (target[0] - pred_x) + random.uniform(
                -noise_scale, noise_scale
            )
            pred_y += lr * (target[1] - pred_y) + random.uniform(
                -noise_scale, noise_scale
            )
            pred = (int(round(pred_x)), int(round(pred_y)))

            loss = math.dist(target, pred)

            overlay = render_overlay(target, pred)
            wandb.log(
                {
                    "loss": loss,
                    "target_x": target[0],
                    "target_y": target[1],
                    "pred_x": pred[0],
                    "pred_y": pred[1],
                    "overlay": wandb.Image(
                        overlay, caption=f"step={epoch}, loss={loss:.2f}"
                    ),
                },
                step=epoch,
            )
            time.sleep(0.2)

        wandb.finish()


if __name__ == "__main__":
    main()
