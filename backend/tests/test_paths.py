import unittest
from fastapi import HTTPException
from pathlib import Path
import tempfile
import os
from backend.app.core.paths import ensure_within_workspace


class PathEnforcementTests(unittest.TestCase):
    def setUp(self):
        # Create a temp directory to simulate the workspace
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace = str(Path(self.temp_dir.name).resolve()).replace("\\", "/")
        
        # Create some folders and files inside the workspace
        self.sub_dir = Path(self.workspace) / "subdir"
        self.sub_dir.mkdir(exist_ok=True)
        self.valid_file = self.sub_dir / "file.txt"
        self.valid_file.write_text("content", encoding="utf-8")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_legitimate_path_inside_workspace(self):
        # absolute path
        res = ensure_within_workspace(self.workspace, str(self.valid_file))
        self.assertEqual(res.resolve(), self.valid_file.resolve())
        
        # relative path
        res_rel = ensure_within_workspace(self.workspace, "subdir/file.txt")
        self.assertEqual(res_rel.resolve(), self.valid_file.resolve())

    def test_relative_path_escaping_traversal(self):
        # attempts to escape using ../
        with self.assertRaises(HTTPException) as ctx:
            ensure_within_workspace(self.workspace, "subdir/../../outside.txt")
        self.assertEqual(ctx.exception.status_code, 403)
        self.assertEqual(ctx.exception.detail, "Path is outside workspace")

    def test_absolute_path_outside_workspace(self):
        # attempts to escape using an absolute outside path
        outside_path = "/usr/bin/passwd" if os.name != "nt" else "C:/Windows/System32/cmd.exe"
        with self.assertRaises(HTTPException) as ctx:
            ensure_within_workspace(self.workspace, outside_path)
        self.assertEqual(ctx.exception.status_code, 403)
        self.assertEqual(ctx.exception.detail, "Path is outside workspace")

    def test_relative_path_resolution(self):
        # relative path resolution must be under the workspace root
        res = ensure_within_workspace(self.workspace, "newfile.txt")
        expected = Path(self.workspace) / "newfile.txt"
        self.assertEqual(res.resolve(), expected.resolve())


if __name__ == "__main__":
    unittest.main()
