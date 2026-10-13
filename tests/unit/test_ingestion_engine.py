import hashlib
import os
from pathlib import Path
import tempfile
import pytest

from engines.ingestion.filters import (
    GitIgnoreFilter,
    detect_language,
    is_binary_file,
)
from engines.ingestion.models import IngestionConfig
from engines.ingestion.scanner import CodebaseScanner


def test_gitignore_filter_matching():
    """Verify .gitignore filtering rules including directory patterns and negation."""
    patterns = [
        "# This is a comment",
        "",
        "*.log",
        "build/",
        "/root_only.txt",
        "docs/**/*.tmp",
        "!important.log",
    ]
    filter_ = GitIgnoreFilter(patterns)

    # Wildcard
    assert filter_.is_ignored("app.log") is True
    assert filter_.is_ignored("nested/deep/app.log") is True

    # Negation
    assert filter_.is_ignored("important.log") is False

    # Directory only
    assert filter_.is_ignored("build", is_dir=True) is True
    assert filter_.is_ignored("build/artifact.js", is_dir=False) is True

    # Anchored
    assert filter_.is_ignored("root_only.txt") is True
    assert filter_.is_ignored("nested/root_only.txt") is False

    # Double wildcard
    assert filter_.is_ignored("docs/a/b/file.tmp") is True
    assert filter_.is_ignored("other/file.tmp") is False


def test_binary_detection(tmp_path: Path):
    """Verify binary detection by extension and null-byte heuristics."""
    # Known binary extension
    bin_file = tmp_path / "image.png"
    bin_file.write_bytes(b"\x89PNG\r\n\x1a\n")
    assert is_binary_file(bin_file) is True

    # Text file
    txt_file = tmp_path / "script.py"
    txt_file.write_text("print('hello world')", encoding="utf-8")
    assert is_binary_file(txt_file) is False

    # Unknown extension with null byte
    unknown_bin = tmp_path / "custom.dat"
    unknown_bin.write_bytes(b"DATA\x00\x01\x02")
    assert is_binary_file(unknown_bin) is True

    # Unknown extension with text
    unknown_txt = tmp_path / "custom.conf"
    unknown_txt.write_bytes(b"KEY=VALUE\n")
    assert is_binary_file(unknown_txt) is False


def test_language_detection():
    """Verify language classification by extension and standard filenames."""
    assert detect_language(Path("main.py")) == "Python"
    assert detect_language(Path("app.tsx")) == "TypeScript"
    assert detect_language(Path("index.js")) == "JavaScript"
    assert detect_language(Path("style.css")) == "CSS"
    assert detect_language(Path("query.sql")) == "SQL"
    assert detect_language(Path("lib.rs")) == "Rust"
    assert detect_language(Path("main.go")) == "Go"
    assert detect_language(Path("README.md")) == "Markdown"
    assert detect_language(Path("Dockerfile")) == "Dockerfile"
    assert detect_language(Path("Makefile")) == "Makefile"
    assert detect_language(Path("config.toml")) == "TOML"
    assert detect_language(Path("data.json")) == "JSON"
    assert detect_language(Path("no_ext")) == "Plain Text"


def test_line_count_semantics(tmp_path: Path):
    """Verify precise line-count semantics across empty, single-line, and trailing newlines."""
    scanner = CodebaseScanner()

    # Empty file: 0 lines
    empty = tmp_path / "empty.py"
    empty.write_text("", encoding="utf-8")

    # One line no trailing newline: 1 line (1 code, 0 blank)
    one_no_nl = tmp_path / "one_no_nl.py"
    one_no_nl.write_text("code = 1", encoding="utf-8")

    # One line with trailing newline: 1 line (1 code, 0 blank)
    one_with_nl = tmp_path / "one_with_nl.py"
    one_with_nl.write_text("code = 1\n", encoding="utf-8")

    # Multiple lines with blanks
    multi = tmp_path / "multi.py"
    multi.write_text("code1 = 1\n\ncode2 = 2\n", encoding="utf-8")

    summary = scanner.scan(tmp_path)
    file_map = {f.name: f for f in summary.files}

    assert file_map["empty.py"].total_lines == 0
    assert file_map["empty.py"].code_lines == 0
    assert file_map["empty.py"].blank_lines == 0

    assert file_map["one_no_nl.py"].total_lines == 1
    assert file_map["one_no_nl.py"].code_lines == 1
    assert file_map["one_no_nl.py"].blank_lines == 0

    assert file_map["one_with_nl.py"].total_lines == 1
    assert file_map["one_with_nl.py"].code_lines == 1
    assert file_map["one_with_nl.py"].blank_lines == 0

    assert file_map["multi.py"].total_lines == 3
    assert file_map["multi.py"].code_lines == 2
    assert file_map["multi.py"].blank_lines == 1


def test_invalid_utf8_handling(tmp_path: Path):
    """Verify non-UTF-8 text files are safely cataloged without raising decoding exceptions."""
    non_utf8 = tmp_path / "latin.py"
    # ISO-8859-1 encoded string with accented character
    non_utf8.write_bytes(b"# Comment with accent: caf\xe9\nx = 1\n")

    scanner = CodebaseScanner()
    summary = scanner.scan(tmp_path)

    assert summary.included_files_count == 1
    desc = summary.files[0]
    assert desc.name == "latin.py"
    assert desc.total_lines == 2
    assert desc.code_lines == 2
    assert len(desc.sha256) == 64


def test_scanner_default_exclusions_and_gitignore(tmp_path: Path):
    """Verify default ignored directories and local .gitignore are respected."""
    # Valid source file
    src = tmp_path / "src"
    src.mkdir()
    (src / "app.py").write_text("print('app')", encoding="utf-8")

    # Default ignored directories
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    (git_dir / "config").write_text("dummy", encoding="utf-8")

    node_modules = tmp_path / "node_modules"
    node_modules.mkdir()
    (node_modules / "pkg.js").write_text("dummy", encoding="utf-8")

    pycache = tmp_path / "__pycache__"
    pycache.mkdir()
    (pycache / "mod.cpython-313.pyc").write_bytes(b"dummy")

    venv = tmp_path / ".venv"
    venv.mkdir()
    (venv / "pyvenv.cfg").write_text("dummy", encoding="utf-8")

    # Local .gitignore
    (tmp_path / ".gitignore").write_text("ignored_file.py\nsecret_dir/\n", encoding="utf-8")
    (tmp_path / "ignored_file.py").write_text("secret", encoding="utf-8")
    secret_dir = tmp_path / "secret_dir"
    secret_dir.mkdir()
    (secret_dir / "data.py").write_text("secret", encoding="utf-8")

    scanner = CodebaseScanner()
    summary = scanner.scan(tmp_path)

    included_paths = [f.path for f in summary.files]
    assert "src/app.py" in included_paths
    assert ".gitignore" in included_paths
    assert not any(p.startswith(".git/") for p in included_paths)
    assert not any(p.startswith("node_modules/") for p in included_paths)
    assert not any(p.startswith("__pycache__/") for p in included_paths)
    assert not any(p.startswith(".venv/") for p in included_paths)
    assert "ignored_file.py" not in included_paths
    assert not any(p.startswith("secret_dir/") for p in included_paths)


def test_file_size_limit_skipping(tmp_path: Path):
    """Verify files exceeding max_file_size_bytes are skipped and reported."""
    small = tmp_path / "small.txt"
    small.write_text("small", encoding="utf-8")

    large = tmp_path / "large.txt"
    large.write_text("a" * 200, encoding="utf-8")

    # Set threshold to 100 bytes
    config = IngestionConfig(max_file_size_bytes=100)
    scanner = CodebaseScanner(config=config)
    summary = scanner.scan(tmp_path)

    included_names = [f.name for f in summary.files]
    assert "small.txt" in included_names
    assert "large.txt" not in included_names

    skipped_reasons = {s.path: s.reason for s in summary.skipped_files}
    assert skipped_reasons.get("large.txt") == "file_too_large"


def test_scan_truncation_limit(tmp_path: Path):
    """Verify scan truncation when reaching max_total_files limit."""
    for i in range(5):
        (tmp_path / f"file_{i}.txt").write_text(f"content {i}", encoding="utf-8")

    # Set maximum files to 3
    config = IngestionConfig(max_total_files=3)
    scanner = CodebaseScanner(config=config)
    summary = scanner.scan(tmp_path)

    assert summary.is_truncated is True
    assert summary.included_files_count == 3


def test_symlink_escape_prevention(tmp_path: Path):
    """Verify symlinks pointing outside the repository root are skipped."""
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    outside_file = outside_dir / "secret.txt"
    outside_file.write_text("classified", encoding="utf-8")

    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "normal.py").write_text("x = 1", encoding="utf-8")

    # Create symlink pointing outside
    symlink_path = repo_root / "linked_secret.txt"
    try:
        os.symlink(outside_file, symlink_path)
    except (OSError, NotImplementedError):
        pytest.skip("Symlink creation not permitted or supported on this system")

    scanner = CodebaseScanner()
    summary = scanner.scan(repo_root)

    included_names = [f.name for f in summary.files]
    assert "normal.py" in included_names
    assert "linked_secret.txt" not in included_names

    skipped_reasons = {s.path: s.reason for s in summary.skipped_files}
    assert skipped_reasons.get("linked_secret.txt") == "symlink_outside_root"


def test_scanner_invalid_path_errors():
    """Verify non-existent and non-directory paths raise appropriate exceptions."""
    scanner = CodebaseScanner()
    with pytest.raises(FileNotFoundError):
        scanner.scan(Path("non_existent_directory_xyz_123"))

    # File instead of directory
    with tempfile.NamedTemporaryFile() as tmp:
        with pytest.raises(NotADirectoryError):
            scanner.scan(Path(tmp.name))


def test_symlink_escape_detection_cross_platform(tmp_path: Path):
    """Verify scanner detects and skips external symlinks across all platforms including Windows non-admin."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "valid.py").write_text("print('safe')\n", encoding="utf-8")
    outside_file = tmp_path / "secret.txt"
    outside_file.write_text("secret_content\n", encoding="utf-8")

    fake_link = repo_root / "symlink_escape.py"
    fake_link.write_text("dummy", encoding="utf-8")

    from unittest.mock import MagicMock, patch

    real_scandir = os.scandir

    def mocked_scandir(path):
        entries = list(real_scandir(path))
        for i, entry in enumerate(entries):
            if entry.name == "symlink_escape.py":
                mock_entry = MagicMock()
                mock_entry.name = entry.name
                mock_entry.path = entry.path
                mock_entry.is_symlink.return_value = True
                mock_entry.is_dir.return_value = False
                mock_entry.is_file.return_value = True
                mock_entry.stat.return_value = entry.stat()
                entries[i] = mock_entry
        return entries

    orig_resolve = Path.resolve

    def mocked_resolve(self, *args, **kwargs):
        if self.name == "symlink_escape.py":
            return outside_file.resolve()
        return orig_resolve(self, *args, **kwargs)

    with patch("os.scandir", side_effect=mocked_scandir), patch.object(Path, "resolve", mocked_resolve):
        scanner = CodebaseScanner()
        summary = scanner.scan(repo_root)

    included_names = [f.name for f in summary.files]
    assert "valid.py" in included_names
    assert "symlink_escape.py" not in included_names

    skipped_reasons = {s.path: s.reason for s in summary.skipped_files}
    assert skipped_reasons.get("symlink_escape.py") == "symlink_outside_root"
