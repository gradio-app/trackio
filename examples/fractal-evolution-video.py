#!/usr/bin/env python3
"""
Fractal Evolution Video Example with trackio.Video

This example demonstrates how to use trackio.Video to track the evolution of
fractals with different parameters. It shows how small changes in parameters
can dramatically affect the visual output of mathematical fractals.

The example shows:
1. How different fractal parameters affect pattern generation
2. Batch video logging with trackio.Video
3. Parameter tracking and comparison
"""

import random

import numpy as np

import trackio


class FractalGenerator:
    """Generate various types of fractals with different parameters."""

    def __init__(
        self,
        width: int = 256,
        height: int = 256,
        fractal_type: str = "mandelbrot",
        max_iterations: int = 100,
        zoom: float = 1.0,
        center_x: float = 0.0,
        center_y: float = 0.0,
        color_scheme: str = "classic",
    ):
        self.width = width
        self.height = height
        self.fractal_type = fractal_type
        self.max_iterations = max_iterations
        self.zoom = zoom
        self.center_x = center_x
        self.center_y = center_y
        self.color_scheme = color_scheme

        self.x_coords = np.linspace(-2 / zoom + center_x, 2 / zoom + center_x, width)
        self.y_coords = np.linspace(-2 / zoom + center_y, 2 / zoom + center_y, height)
        self.X, self.Y = np.meshgrid(self.x_coords, self.y_coords)

    def generate_fractal(self) -> np.ndarray:
        """Generate the fractal based on the current parameters using vectorized operations."""
        C = self.X + 1j * self.Y

        if self.fractal_type == "mandelbrot":
            fractal = self.mandelbrot_vectorized(C)
        elif self.fractal_type == "julia":
            c = complex(-0.7, 0.27015)
            fractal = self.julia_vectorized(C, c)
        elif self.fractal_type == "burning_ship":
            fractal = self.burning_ship_vectorized(C)

        return fractal

    def mandelbrot_vectorized(self, C: np.ndarray) -> np.ndarray:
        """Vectorized Mandelbrot set computation."""
        Z = np.zeros_like(C)
        fractal = np.zeros(C.shape, dtype=np.float32)

        for i in range(self.max_iterations):
            mask = np.abs(Z) <= 2
            Z[mask] = Z[mask] * Z[mask] + C[mask]
            fractal[mask] = i

        return fractal

    def julia_vectorized(self, Z: np.ndarray, c: complex) -> np.ndarray:
        """Vectorized Julia set computation."""
        fractal = np.zeros(Z.shape, dtype=np.float32)

        for i in range(self.max_iterations):
            mask = np.abs(Z) <= 2
            Z[mask] = Z[mask] * Z[mask] + c
            fractal[mask] = i

        return fractal

    def burning_ship_vectorized(self, C: np.ndarray) -> np.ndarray:
        """Vectorized Burning Ship fractal computation."""
        Z = np.zeros_like(C)
        fractal = np.zeros(C.shape, dtype=np.float32)

        for i in range(self.max_iterations):
            mask = np.abs(Z) <= 2
            Z[mask] = (np.abs(Z[mask].real) + 1j * np.abs(Z[mask].imag)) ** 2 + C[mask]
            fractal[mask] = i

        return fractal

    def apply_color_scheme(self, fractal: np.ndarray) -> np.ndarray:
        """Apply color scheme to the fractal with smooth gradients."""
        normalized = fractal / self.max_iterations

        if self.color_scheme == "classic":
            colors = np.zeros((self.height, self.width, 3), dtype=np.uint8)
            blue_intensity = (0.5 + 0.5 * np.sin(normalized * 4 * np.pi)) * 255
            colors[:, :, 0] = (blue_intensity * 0.3).astype(np.uint8)
            colors[:, :, 1] = (blue_intensity * 0.6).astype(np.uint8)
            colors[:, :, 2] = blue_intensity.astype(np.uint8)
            return colors

        elif self.color_scheme == "fire":
            colors = np.zeros((self.height, self.width, 3), dtype=np.uint8)
            fire_phase = normalized * 3 * np.pi
            colors[:, :, 0] = 255
            colors[:, :, 1] = (128 + 127 * np.sin(fire_phase)).astype(np.uint8)
            colors[:, :, 2] = (64 * np.sin(fire_phase * 0.5)).astype(np.uint8)
            return colors

        elif self.color_scheme == "rainbow":
            colors = np.zeros((self.height, self.width, 3), dtype=np.uint8)
            rainbow_phase = normalized * 6 * np.pi
            red_phase = rainbow_phase % (2 * np.pi)
            colors[:, :, 0] = np.where(
                red_phase < np.pi,
                (255 * red_phase / np.pi).astype(np.uint8),
                (255 * (2 * np.pi - red_phase) / np.pi).astype(np.uint8),
            )

            green_phase = (rainbow_phase + 2 * np.pi / 3) % (2 * np.pi)
            colors[:, :, 1] = np.where(
                green_phase < np.pi,
                (255 * green_phase / np.pi).astype(np.uint8),
                (255 * (2 * np.pi - green_phase) / np.pi).astype(np.uint8),
            )

            blue_phase = (rainbow_phase + 4 * np.pi / 3) % (2 * np.pi)
            colors[:, :, 2] = np.where(
                blue_phase < np.pi,
                (255 * blue_phase / np.pi).astype(np.uint8),
                (255 * (2 * np.pi - blue_phase) / np.pi).astype(np.uint8),
            )

            return colors

        elif self.color_scheme == "monochrome":
            colors = np.zeros((self.height, self.width, 3), dtype=np.uint8)
            gray_intensity = (0.3 + 0.7 * np.sin(normalized * 2 * np.pi)) * 255
            colors[:, :, 0] = gray_intensity.astype(np.uint8)
            colors[:, :, 1] = gray_intensity.astype(np.uint8)
            colors[:, :, 2] = gray_intensity.astype(np.uint8)
            return colors

        else:
            return self.apply_color_scheme(fractal)


def generate_fractal_video(
    num_frames: int = 60, width: int = 256, height: int = 256, **fractal_params
) -> np.ndarray:
    """
    Generate a video of fractal evolution with changing parameters.

    Args:
        num_frames: Number of frames to generate
        width: Fractal width
        height: Fractal height
        **fractal_params: Parameters for FractalGenerator

    Returns:
        Video array in (F, C, H, W) format
    """
    video = np.zeros((num_frames, 3, height, width), dtype=np.uint8)

    fractal_type = fractal_params.get("fractal_type", "mandelbrot")
    max_iterations = fractal_params.get("max_iterations", 100)
    zoom = fractal_params.get("zoom", 1.0)
    center_x = fractal_params.get("center_x", 0.0)
    center_y = fractal_params.get("center_y", 0.0)
    color_scheme = fractal_params.get("color_scheme", "classic")

    zoom_animation = fractal_params.get("zoom_animation", False)
    center_animation = fractal_params.get("center_animation", False)
    iteration_animation = fractal_params.get("iteration_animation", False)

    for frame in range(num_frames):
        progress = frame / (num_frames - 1)
        current_zoom = zoom
        current_center_x = center_x
        current_center_y = center_y
        current_max_iterations = max_iterations

        if zoom_animation:
            zoom_cycle = progress * 2 * np.pi
            zoom_factor = 1 + 9 * (0.5 * (1 + np.sin(zoom_cycle)))
            current_zoom = zoom * zoom_factor

        if center_animation:
            center_cycle = progress * 2 * np.pi
            current_center_x = center_x + 0.4 * np.sin(center_cycle)
            current_center_y = center_y + 0.4 * np.cos(center_cycle)

        if iteration_animation:
            iter_cycle = progress * 2 * np.pi
            iter_factor = 1 + 0.5 * (0.5 * (1 + np.sin(iter_cycle)))
            current_max_iterations = int(max_iterations * iter_factor)

        generator = FractalGenerator(
            width=width,
            height=height,
            fractal_type=fractal_type,
            max_iterations=current_max_iterations,
            zoom=current_zoom,
            center_x=current_center_x,
            center_y=current_center_y,
            color_scheme=color_scheme,
        )

        fractal = generator.generate_fractal()
        colored_fractal = generator.apply_color_scheme(fractal)

        video[frame] = np.transpose(colored_fractal, (2, 0, 1))

    return video


def main():
    parameter_sets = [
        {
            "name": "Mandelbrot",
            "fractal_type": "mandelbrot",
            "max_iterations": 120,
            "zoom": 0.5,
            "center_x": -0.75,
            "center_y": 0.1,
            "color_scheme": "classic",
            "zoom_animation": True,
            "center_animation": False,
            "iteration_animation": False,
        },
        {
            "name": "Julia",
            "fractal_type": "julia",
            "max_iterations": 100,
            "zoom": 0.8,
            "center_x": 0.0,
            "center_y": 0.0,
            "color_scheme": "fire",
            "zoom_animation": True,
            "center_animation": True,
            "iteration_animation": False,
        },
        {
            "name": "Burning_Ship",
            "fractal_type": "burning_ship",
            "max_iterations": 150,
            "zoom": 0.3,
            "center_x": -1.75,
            "center_y": 0.0,
            "color_scheme": "rainbow",
            "zoom_animation": True,
            "center_animation": False,
            "iteration_animation": True,
        },
        {
            "name": "Mandelbrot Edge Exploration",
            "fractal_type": "mandelbrot",
            "max_iterations": 200,
            "zoom": 0.2,
            "center_x": -0.8,
            "center_y": 0.156,
            "color_scheme": "monochrome",
            "zoom_animation": True,
            "center_animation": True,
            "iteration_animation": True,
        },
    ]

    project_id = random.randint(100000, 999999)
    trackio.init(
        project=f"fractal-evolution-video-{project_id}",
        name="fractal-parameter-comparison",
    )

    fractal_videos = []

    for i, params in enumerate(parameter_sets):
        print(f"Generating fractal {i + 1}/{len(parameter_sets)}: {params['name']}")

        video = generate_fractal_video(
            num_frames=120,
            width=256,
            height=256,
            **{k: v for k, v in params.items() if k != "name"},
        )

        fractal_videos.append(video)

        video_obj = trackio.Video(video, caption=params["name"], fps=15)

        trackio.log(
            {
                "video": video_obj,
                "fractal_type": params["fractal_type"],
                "max_iterations": params["max_iterations"],
                "zoom": params["zoom"],
                "center_x": params["center_x"],
                "center_y": params["center_y"],
                "parameter_set": params["name"],
            }
        )

    print("Creating batch comparison video...")
    batch_video = np.stack(fractal_videos, axis=0)

    batch_video_obj = trackio.Video(
        batch_video, caption="Fractal Evolution Parameter Comparison", fps=15
    )

    trackio.log(
        {
            "comparison_video": batch_video_obj,
        }
    )

    print("Fractal evolution video example completed!")
    print(f"Generated {len(parameter_sets)} fractal videos")
    print("Check the trackio dashboard to view the results!")

    trackio.finish()


if __name__ == "__main__":
    main()
