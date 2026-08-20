"""
inventory_generator.py — File inventory generator for repository scanning.
"""

SOURCE_EXTENSIONS = [".py", ".js", ".ts", ".jsx", ".tsx", ".yaml"]


def get_source_extensions() -> list[str]:
    return SOURCE_EXTENSIONS.copy()
