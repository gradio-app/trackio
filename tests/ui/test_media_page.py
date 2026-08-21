import numpy as np
import pytest
from playwright.sync_api import expect, sync_playwright

import trackio


def _write_glb(path):
    import json
    import struct

    positions = [(0, 0, 0), (1, 0, 0), (0, 1, 0)]
    vertex_bytes = b"".join(struct.pack("<3f", *p) for p in positions)
    index_bytes = struct.pack("<3H", 0, 1, 2)
    padding = b"\x00" * ((4 - len(index_bytes) % 4) % 4)
    blob = index_bytes + padding + vertex_bytes
    document = {
        "asset": {"version": "2.0"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0}],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 1}, "indices": 0}]}],
        "buffers": [{"byteLength": len(blob)}],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": len(index_bytes)},
            {
                "buffer": 0,
                "byteOffset": len(index_bytes) + len(padding),
                "byteLength": len(vertex_bytes),
            },
        ],
        "accessors": [
            {"bufferView": 0, "componentType": 5123, "count": 3, "type": "SCALAR"},
            {
                "bufferView": 1,
                "componentType": 5126,
                "count": 3,
                "type": "VEC3",
                "min": [0, 0, 0],
                "max": [1, 1, 0],
            },
        ],
    }
    json_chunk = json.dumps(document, separators=(",", ":")).encode()
    json_chunk += b" " * ((4 - len(json_chunk) % 4) % 4)
    binary_chunk = blob + b"\x00" * ((4 - len(blob) % 4) % 4)
    glb = struct.pack(
        "<4sII", b"glTF", 2, 12 + 8 + len(json_chunk) + 8 + len(binary_chunk)
    )
    glb += struct.pack("<II", len(json_chunk), 0x4E4F534A) + json_chunk
    glb += struct.pack("<II", len(binary_chunk), 0x004E4942) + binary_chunk
    path.write_bytes(glb)
    return path


@pytest.fixture
def media_run(temp_dir, tmp_path):
    project = "test-media-page"
    run = trackio.init(project=project, name="media-run")
    run.log(
        {
            "image": trackio.Image(
                np.random.randint(0, 255, (32, 32, 3), dtype=np.uint8),
                caption="An image",
            ),
            "cloud": trackio.Object3D(
                np.array([[0, 0, 0, 255, 80, 40], [1, 1, 1, 40, 160, 255]]),
                caption="Direct cloud",
            ),
            "mesh": trackio.Object3D(
                _write_glb(tmp_path / "tri.glb"), caption="Triangle mesh"
            ),
            "samples": trackio.Table(
                columns=["model"],
                data=[[trackio.Object3D(np.array([[0, 0, 0], [0, 1, 0], [1, 0, 0]]))]],
            ),
        }
    )
    run.finish()
    app, _, _, full_url = trackio.show(
        project=project, block_thread=False, open_browser=False
    )
    try:
        yield full_url
    finally:
        trackio.delete_project(project, force=True)
        app.close()


def test_media_page_shows_every_media_type(media_run):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        page.set_default_timeout(15_000)
        page.goto(media_run)
        page.get_by_role("button", name="Media & Tables", exact=True).click()

        expect(page.locator(".gallery img").first).to_be_visible()
        expect(page.get_by_text("3D Objects (2)")).to_be_visible()
        expect(page.locator(".object-card")).to_have_count(2)
        expect(page.locator(".object-frame.compact")).to_have_count(1)
        expect(page.get_by_role("button", name="Open", exact=True)).to_have_count(0)
        expect(page.locator("canvas[aria-label='Interactive 3D scene']")).to_have_count(
            0
        )
        browser.close()


@pytest.mark.parametrize("caption", ["Direct cloud", "Triangle mesh"])
def test_object3d_viewer_opens_renders_and_disposes(media_run, caption):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        page.set_default_timeout(15_000)
        errors = []
        page.on(
            "console",
            lambda message: (
                errors.append(message.text) if message.type == "error" else None
            ),
        )
        page.goto(media_run)
        page.get_by_role("button", name="Media & Tables", exact=True).click()

        card = page.locator(".object-card").filter(has_text=caption)
        frame = card.locator(".object-frame")
        assert frame.evaluate("el => getComputedStyle(el).cursor") == "zoom-in"
        frame.click()

        expect(
            page.get_by_role("dialog", name=f"3D viewer for {caption}")
        ).to_be_visible()
        canvas = page.locator("canvas[aria-label='Interactive 3D scene']")
        expect(canvas).to_have_count(1)
        expect(page.locator(".status")).to_have_count(0)

        page.get_by_role("button", name="Grid", exact=True).click()
        page.get_by_role("button", name="Reset camera", exact=True).click()
        page.keyboard.press("Escape")
        expect(canvas).to_have_count(0)

        assert errors == []
        browser.close()


def test_reset_camera_restores_the_initial_view(media_run):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.set_default_timeout(15_000)
        page.goto(media_run)
        page.get_by_role("button", name="Media & Tables", exact=True).click()

        page.locator(".object-card").filter(has_text="Direct cloud").locator(
            ".object-frame"
        ).click()
        canvas = page.locator("canvas[aria-label='Interactive 3D scene']")
        expect(canvas).to_have_count(1)
        expect(page.locator(".status")).to_have_count(0)
        page.wait_for_timeout(1500)
        initial = canvas.screenshot()

        box = canvas.bounding_box()
        page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        page.mouse.down()
        page.mouse.move(
            box["x"] + box["width"] / 2 + 180, box["y"] + box["height"] / 2 + 90
        )
        page.mouse.up()
        page.wait_for_timeout(1500)
        orbited = canvas.screenshot()
        assert orbited != initial, "dragging the canvas should orbit the camera"

        page.get_by_role("button", name="Reset camera", exact=True).click()
        page.wait_for_timeout(1500)
        assert canvas.screenshot() == initial, "Reset camera should restore the view"

        browser.close()
