#!/usr/bin/env python3
"""Phase 10.8: App Icon Transparency Fix.

Removes the outer solid black background from CODE OS icon assets using
connected-region flood fill from the borders/corners, preserving anti-aliased
edge feathering and keeping 100% of the interior circular logo byte-identical.
Regenerates build/icon.png (512x512), build/icon_256.png (256x256), and
build/icon.ico (with 16, 24, 32, 48, 64, 128, 256 sizes with alpha).
"""

from __future__ import annotations

from collections import deque
import hashlib
from pathlib import Path
import sys

import numpy as np
from PIL import Image

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MASTER_ICON = PROJECT_ROOT / "build" / "icon.png"

# Circle geometry on 512x512 canvas
CANVAS_SIZE = 512
CENTER = (255.5, 255.5)  # (w-1)/2, (h-1)/2
R_INNER = 239.5  # Inner boundary of anti-aliased edge (inside is 100% untouched)
R_OUTER = 241.5  # Outer boundary of anti-aliased edge (outside is 100% transparent)
CROP_SIZE = 256  # Center crop box size for byte-identical integrity check

ICO_SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]


def process_icon_alpha(src_img: Image.Image) -> tuple[Image.Image, dict]:
    """Process master icon to remove outer black background via border flood-fill."""
    rgba = src_img.convert("RGBA")
    src_arr = np.array(rgba)
    h, w = src_arr.shape[:2]
    cx, cy = CENTER

    y, x = np.ogrid[:h, :w]
    dist = np.sqrt((x - cx) ** 2 + (y - cy) ** 2)

    # 1. Connected-region flood fill from all 4 borders & corners
    # Outer black region is connected to borders with dist >= R_INNER
    visited = np.zeros((h, w), dtype=bool)
    queue: deque[tuple[int, int]] = deque()

    # Seed all border pixels
    for col in range(w):
        visited[0, col] = True
        queue.append((0, col))
        visited[h - 1, col] = True
        queue.append((h - 1, col))
    for row in range(h):
        if not visited[row, 0]:
            visited[row, 0] = True
            queue.append((row, 0))
        if not visited[row, w - 1]:
            visited[row, w - 1] = True
            queue.append((row, w - 1))

    # BFS flood fill bounded by R_INNER to never leak into interior logo
    while queue:
        r_cur, c_cur = queue.popleft()
        for dr, dc in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            nr, nc = r_cur + dr, c_cur + dc
            if 0 <= nr < h and 0 <= nc < w and not visited[nr, nc]:
                if dist[nr, nc] >= R_INNER:
                    visited[nr, nc] = True
                    queue.append((nr, nc))

    # 2. Modify alpha channel based on connected flood-fill region
    dst_arr = src_arr.copy()

    # Fully outer region connected to border: alpha = 0
    outer_mask = visited & (dist >= R_OUTER)
    dst_arr[outer_mask, 3] = 0

    # Anti-aliased transition band connected to border: feather alpha
    feather_mask = visited & (dist >= R_INNER) & (dist < R_OUTER)
    factor = (R_OUTER - dist[feather_mask]) / (R_OUTER - R_INNER)
    dst_arr[feather_mask, 3] = np.clip(np.round(factor * 255.0), 0, 255).astype(np.uint8)

    # All pixels with dist < R_INNER were not visited by flood-fill:
    # They remain 100% byte-identical to source

    # 3. Integrity Checks
    # E3.1: Corner pixels alpha == 0
    corners = [
        int(dst_arr[0, 0, 3]),
        int(dst_arr[0, w - 1, 3]),
        int(dst_arr[h - 1, 0, 3]),
        int(dst_arr[h - 1, w - 1, 3]),
    ]
    assert all(a == 0 for a in corners), f"Corner alpha check failed: {corners}"

    # E3.2: Center pixel alpha == 255
    center_alpha = int(dst_arr[int(cy), int(cx), 3])
    assert center_alpha == 255, f"Center alpha check failed: {center_alpha}"

    # E3.3: Interior circle region byte-identical to source interior
    box_half = CROP_SIZE // 2
    r_start, r_end = int(cy) - box_half, int(cy) + box_half
    c_start, c_end = int(cx) - box_half, int(cx) + box_half

    crop_src = src_arr[r_start:r_end, c_start:c_end]
    crop_dst = dst_arr[r_start:r_end, c_start:c_end]

    src_hash = hashlib.sha256(crop_src.tobytes()).hexdigest()
    dst_hash = hashlib.sha256(crop_dst.tobytes()).hexdigest()
    assert src_hash == dst_hash, (
        f"Interior crop mismatch! src={src_hash} dst={dst_hash}"
    )

    stats = {
        "corners_alpha": corners,
        "center_alpha": center_alpha,
        "interior_hash": src_hash,
        "transparent_pixels": int((dst_arr[:, :, 3] == 0).sum()),
        "feathered_pixels": int(feather_mask.sum()),
        "opaque_pixels": int((dst_arr[:, :, 3] == 255).sum()),
    }

    out_img = Image.fromarray(dst_arr, mode="RGBA")
    return out_img, stats


def main() -> int:
    print(f"Loading master icon from {MASTER_ICON}...")
    if not MASTER_ICON.exists():
        print(f"Error: {MASTER_ICON} not found!", file=sys.stderr)
        return 1

    src_img = Image.open(MASTER_ICON)
    fixed_512, stats = process_icon_alpha(src_img)
    print("Integrity checks passed:")
    print(f"  - Corner alphas: {stats['corners_alpha']}")
    print(f"  - Center alpha: {stats['center_alpha']}")
    print(f"  - Interior hash (256x256 center crop): {stats['interior_hash']}")
    print(f"  - Fully transparent pixels: {stats['transparent_pixels']}")
    print(f"  - Feathered edge pixels: {stats['feathered_pixels']}")
    print(f"  - Fully opaque pixels: {stats['opaque_pixels']}")

    # 1. Save build/icon.png (512x512)
    fixed_512.save(MASTER_ICON, format="PNG")
    print(f"Saved {MASTER_ICON} (512x512)")

    # 2. Save build/icon_256.png (256x256)
    icon_256_path = PROJECT_ROOT / "build" / "icon_256.png"
    icon_256 = fixed_512.resize((256, 256), Image.Resampling.LANCZOS)
    icon_256.save(icon_256_path, format="PNG")
    print(f"Saved {icon_256_path} (256x256)")

    # 3. Save build/icon.ico with all required sizes
    ico_path = PROJECT_ROOT / "build" / "icon.ico"
    fixed_512.save(ico_path, format="ICO", sizes=ICO_SIZES)
    print(f"Saved {ico_path} (sizes: {[s[0] for s in ICO_SIZES]})")

    # 4. Update copies across the project
    copies = [
        PROJECT_ROOT / "dist" / "icon.png",
        PROJECT_ROOT / "public" / "icon.png",
        PROJECT_ROOT / "public" / "codeos-app-icon.png",
        PROJECT_ROOT / "dist" / "codeos-app-icon.png",
    ]
    for target in copies:
        if target.parent.exists():
            fixed_512.save(target, format="PNG")
            print(f"Updated copy: {target}")

    print("\nIcon transparency regeneration complete successfully.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
