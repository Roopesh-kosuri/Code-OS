from __future__ import annotations
from pathlib import Path
import pytest

LF = chr(10)
CR = chr(13)
CRLF = CR + LF
DENSE_LF = 'def foo():' + LF + '    return 1' + LF + 'result = foo()' + LF + 'print(result)' + LF
DENSE_CRLF = DENSE_LF.replace(LF, CRLF)
DENSE_MIXED = 'def foo():' + CRLF + '    return 1' + LF + 'result = foo()' + CRLF + 'print(result)' + LF


class TestNormalizeEol:
    @pytest.fixture(autouse=True)
    def _import_fn(self):
        from app.features.files.service import _normalize_eol
        self.n = _normalize_eol

    def test_lf_unchanged(self):
        assert self.n(DENSE_LF) == DENSE_LF

    def test_crlf_to_lf(self):
        r = self.n(DENSE_CRLF)
        assert CR not in r and r == DENSE_LF

    def test_mixed_no_cr(self):
        assert CR not in self.n(DENSE_MIXED)

    def test_bare_cr(self):
        assert self.n('a' + CR + 'b' + CR + 'c' + CR) == 'a' + LF + 'b' + LF + 'c' + LF

    def test_empty(self):
        assert self.n('') == ''

    def test_no_double_newlines(self):
        assert LF + LF not in self.n(DENSE_CRLF)


class TestFileOpenPreservesLineCount:
    def test_lf_file_no_extra_newlines(self, tmp_path):
        from app.features.files.service import read_file
        (tmp_path / 'f.py').write_bytes(DENSE_LF.encode())
        c, _ = read_file(str(tmp_path), 'f.py')
        assert c.count(LF) == DENSE_LF.count(LF)

    def test_crlf_file_no_extra_newlines(self, tmp_path):
        from app.features.files.service import read_file
        (tmp_path / 'f.py').write_bytes(DENSE_CRLF.encode())
        c, _ = read_file(str(tmp_path), 'f.py')
        assert c.count(LF) == DENSE_LF.count(LF) and CR not in c

    def test_no_double_spacing_crlf(self, tmp_path):
        from app.features.files.service import read_file
        (tmp_path / 'f.py').write_bytes(DENSE_CRLF.encode())
        c, _ = read_file(str(tmp_path), 'f.py')
        assert LF + LF not in c

    def test_no_double_spacing_lf(self, tmp_path):
        from app.features.files.service import read_file
        (tmp_path / 'f.py').write_bytes(DENSE_LF.encode())
        c, _ = read_file(str(tmp_path), 'f.py')
        assert LF + LF not in c


class TestCloseReopenNoExtraLines:
    def _rt(self, tmp_path, init, n=2):
        from app.features.files.service import read_file, write_file
        write_file(str(tmp_path), 'f.py', init)
        for _ in range(n):
            c, _ = read_file(str(tmp_path), 'f.py')
            write_file(str(tmp_path), 'f.py', c)
        return read_file(str(tmp_path), 'f.py')[0]

    def test_lf_stable(self, tmp_path):
        r = self._rt(tmp_path, DENSE_LF)
        assert LF + LF not in r and r.count(LF) == DENSE_LF.count(LF)

    def test_crlf_stable(self, tmp_path):
        r = self._rt(tmp_path, DENSE_CRLF)
        assert LF + LF not in r and r.count(LF) == DENSE_LF.count(LF)

    def test_mixed_stable(self, tmp_path):
        assert LF + LF not in self._rt(tmp_path, DENSE_MIXED)


class TestWriteTextDoublingPrevention:
    def test_crlf_input_no_rrcrlf_on_disk(self, tmp_path):
        from app.features.files.service import write_file
        write_file(str(tmp_path), 't.py', DENSE_CRLF)
        assert b'\r\r\n' not in (tmp_path / 't.py').read_bytes()

    def test_lf_input_no_rrcrlf_on_disk(self, tmp_path):
        from app.features.files.service import write_file
        write_file(str(tmp_path), 't.py', DENSE_LF)
        assert b'\r\r\n' not in (tmp_path / 't.py').read_bytes()

    def test_corrupted_file_healed_on_read(self, tmp_path):
        from app.features.files.service import read_file
        corrupted = DENSE_CRLF.replace(LF, CRLF)
        (tmp_path / 'c.py').write_bytes(corrupted.encode())
        c, _ = read_file(str(tmp_path), 'c.py')
        assert LF + LF not in c and CR not in c


class TestFileWatcherUpdateNoLineDoubling:
    def test_external_crlf_write_then_read(self, tmp_path):
        from app.features.files.service import read_file
        (tmp_path / 'e.py').write_bytes(DENSE_CRLF.encode())
        c, _ = read_file(str(tmp_path), 'e.py')
        assert LF + LF not in c and CR not in c

    def test_re_read_stable(self, tmp_path):
        from app.features.files.service import read_file
        (tmp_path / 'e.py').write_bytes(DENSE_CRLF.encode())
        c1, _ = read_file(str(tmp_path), 'e.py')
        c2, _ = read_file(str(tmp_path), 'e.py')
        assert c1 == c2


class TestSavePreservesOriginalEolStyle:
    def test_lf_save_read_idempotent(self, tmp_path):
        from app.features.files.service import read_file, write_file
        write_file(str(tmp_path), 'a.py', DENSE_LF)
        c1, _ = read_file(str(tmp_path), 'a.py')
        assert CR not in c1
        write_file(str(tmp_path), 'a.py', c1)
        c2, _ = read_file(str(tmp_path), 'a.py')
        assert c1 == c2

        assert c1 == c2 and LF + LF not in c2


# ---------------------------------------------------------------------------
# Phase 10.6 Required Test Names (Exact Match)
# ---------------------------------------------------------------------------

def test_file_open_preserves_line_count(tmp_path):
    from app.features.files.service import read_file
    (tmp_path / 'f.py').write_bytes(DENSE_CRLF.encode())
    c, _ = read_file(str(tmp_path), 'f.py')
    assert c.count(LF) == DENSE_LF.count(LF)
    assert CR not in c


def test_close_reopen_no_extra_lines(tmp_path):
    from app.features.files.service import read_file, write_file
    write_file(str(tmp_path), 'f.py', DENSE_CRLF)
    for _ in range(3):
        c, _ = read_file(str(tmp_path), 'f.py')
        write_file(str(tmp_path), 'f.py', c)
    final_c, _ = read_file(str(tmp_path), 'f.py')
    assert LF + LF not in final_c
    assert final_c.count(LF) == DENSE_LF.count(LF)


def test_crlf_file_no_double_spacing(tmp_path):
    from app.features.files.service import read_file
    (tmp_path / 'f.py').write_bytes(DENSE_CRLF.encode())
    c, _ = read_file(str(tmp_path), 'f.py')
    assert LF + LF not in c


def test_lf_file_no_double_spacing(tmp_path):
    from app.features.files.service import read_file
    (tmp_path / 'f.py').write_bytes(DENSE_LF.encode())
    c, _ = read_file(str(tmp_path), 'f.py')
    assert LF + LF not in c


def test_mixed_eol_file_normalized_correctly(tmp_path):
    from app.features.files.service import read_file
    (tmp_path / 'f.py').write_bytes(DENSE_MIXED.encode())
    c, _ = read_file(str(tmp_path), 'f.py')
    assert CR not in c
    assert LF + LF not in c


def test_file_watcher_update_no_line_doubling(tmp_path):
    from app.features.files.service import read_file
    (tmp_path / 'f.py').write_bytes(DENSE_CRLF.encode())
    c1, _ = read_file(str(tmp_path), 'f.py')
    (tmp_path / 'f.py').write_bytes(DENSE_CRLF.encode())
    c2, _ = read_file(str(tmp_path), 'f.py')
    assert c1 == c2
    assert LF + LF not in c2


def test_save_preserves_original_eol_style(tmp_path):
    from app.features.files.service import read_file, write_file
    write_file(str(tmp_path), 'f.py', DENSE_LF)
    c1, _ = read_file(str(tmp_path), 'f.py')
    write_file(str(tmp_path), 'f.py', c1)
    c2, _ = read_file(str(tmp_path), 'f.py')
    assert c1 == c2
    assert CR not in c2