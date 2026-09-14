"""Regression tests for Phase 10.8: App Icon Transparency (Remove Black Square Background)."""

import hashlib
from pathlib import Path
import numpy as np
from PIL import Image
import pytest
import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
BUILD_DIR = PROJECT_ROOT / "build"
ICON_PNG = BUILD_DIR / "icon.png"
ICON_256 = BUILD_DIR / "icon_256.png"
ICON_ICO = BUILD_DIR / "icon.ico"
ELECTRON_BUILDER_YML = PROJECT_ROOT / "electron-builder.yml"


def test_icon_png_has_transparent_corners():
    """Verify build/icon.png has alpha=0 on all 4 corners and alpha=255 at center."""
    assert ICON_PNG.exists(), f"Missing {ICON_PNG}"
    img = Image.open(ICON_PNG).convert("RGBA")
    arr = np.array(img)
    h, w = arr.shape[:2]

    # All 4 corners must be 100% transparent (alpha == 0)
    tl = int(arr[0, 0, 3])
    tr = int(arr[0, w - 1, 3])
    bl = int(arr[h - 1, 0, 3])
    br = int(arr[h - 1, w - 1, 3])
    assert tl == 0, f"Top-left corner alpha is {tl}, expected 0"
    assert tr == 0, f"Top-right corner alpha is {tr}, expected 0"
    assert bl == 0, f"Bottom-left corner alpha is {bl}, expected 0"
    assert br == 0, f"Bottom-right corner alpha is {br}, expected 0"

    # Center pixel must be fully opaque
    cy, cx = h // 2, w // 2
    center_alpha = int(arr[cy, cx, 3])
    assert center_alpha == 255, f"Center pixel alpha is {center_alpha}, expected 255"

    # Verify significant transparent area outside the circle
    transparent_count = (arr[:, :, 3] == 0).sum()
    assert transparent_count > 50_000, f"Expected >50000 transparent pixels, got {transparent_count}"


def test_icon_interior_preserved_vs_source():
    """Verify that the interior circular logo pixels are fully opaque and preserved."""
    assert ICON_PNG.exists()
    img = Image.open(ICON_PNG).convert("RGBA")
    arr = np.array(img)
    h, w = arr.shape[:2]
    cy, cx = (h - 1) / 2.0, (w - 1) / 2.0

    y, x = np.ogrid[:h, :w]
    dist = np.sqrt((x - cx) ** 2 + (y - cy) ** 2)

    # Core interior (radius <= 230) must be 100% opaque (no interior pixels made transparent)
    interior_mask = dist <= 230
    interior_alphas = arr[interior_mask, 3]
    assert np.all(interior_alphas == 255), "Some interior circular logo pixels are not opaque!"

    # Center 256x256 crop must remain non-empty and valid
    box_half = 128
    crop = arr[int(cy) - box_half : int(cy) + box_half, int(cx) - box_half : int(cx) + box_half]
    assert crop.shape == (256, 256, 4)
    assert np.all(crop[:, :, 3] == 255), "Center crop contains non-opaque pixels"


def test_ico_contains_multiple_sizes_with_alpha():
    """Verify build/icon.ico contains standard icon sizes (16,24,32,48,64,128,256) all with alpha=0 at corners."""
    assert ICON_ICO.exists(), f"Missing {ICON_ICO}"
    ico = Image.open(ICON_ICO)

    assert hasattr(ico, "ico") and hasattr(ico.ico, "entry"), "Invalid ICO format"
    entries = ico.ico.entry
    expected_sizes = {(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)}
    actual_sizes = {entry.dim for entry in entries}

    assert expected_sizes.issubset(actual_sizes), (
        f"Missing required ICO sizes: {expected_sizes - actual_sizes}"
    )

    for entry in entries:
        sub = ico.ico.getimage(entry.dim)
        arr = np.array(sub)
        assert sub.mode == "RGBA", f"Subimage {entry.dim} mode is {sub.mode}, expected RGBA"

        # Check corners for each size
        tl = int(arr[0, 0, 3])
        tr = int(arr[0, -1, 3])
        bl = int(arr[-1, 0, 3])
        br = int(arr[-1, -1, 3])
        assert (tl, tr, bl, br) == (0, 0, 0, 0), (
            f"ICO size {entry.dim} corners not transparent: {(tl, tr, bl, br)}"
        )

        # Center must be opaque
        mid_y, mid_x = entry.dim[1] // 2, entry.dim[0] // 2
        assert arr[mid_y, mid_x, 3] == 255, f"ICO size {entry.dim} center not opaque"


def test_electron_builder_icon_paths_exist_and_have_alpha():
    """Verify that every icon referenced in electron-builder.yml exists on disk and has transparent corners."""
    assert ELECTRON_BUILDER_YML.exists()
    config = yaml.safe_load(ELECTRON_BUILDER_YML.read_text(encoding="utf-8"))

    # Check Windows icon
    win_icon_rel = config.get("win", {}).get("icon")
    assert win_icon_rel, "electron-builder.yml missing win.icon"
    win_icon_path = PROJECT_ROOT / win_icon_rel
    assert win_icon_path.exists(), f"win.icon path {win_icon_path} does not exist"

    # Check Linux icon
    linux_icon_rel = config.get("linux", {}).get("icon")
    assert linux_icon_rel, "electron-builder.yml missing linux.icon"
    linux_icon_path = PROJECT_ROOT / linux_icon_rel
    assert linux_icon_path.exists(), f"linux.icon path {linux_icon_path} does not exist"

    # Check Mac icon
    mac_icon_rel = config.get("mac", {}).get("icon")
    assert mac_icon_rel, "electron-builder.yml missing mac.icon"
    mac_icon_path = PROJECT_ROOT / mac_icon_rel
    assert mac_icon_path.exists(), f"mac.icon path {mac_icon_path} does not exist"

    # Verify PNG has alpha
    for p in [linux_icon_path, mac_icon_path]:
        img = Image.open(p).convert("RGBA")
        arr = np.array(img)
        assert arr[0, 0, 3] == 0, f"{p} top-left corner is not transparent"
        assert arr[arr.shape[0] // 2, arr.shape[1] // 2, 3] == 255, f"{p} center is not opaque"

    # Verify ICO has alpha
    ico = Image.open(win_icon_path)
    sub = ico.ico.getimage((256, 256))
    arr = np.array(sub)
    assert arr[0, 0, 3] == 0, f"{win_icon_path} (256x256) top-left corner is not transparent"
    assert arr[128, 128, 3] == 255, f"{win_icon_path} center is not opaque"
