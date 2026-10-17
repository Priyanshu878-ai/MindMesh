import io
import os
from pathlib import Path
import zipfile
import pytest

from engines.ingestion.archive import ArchiveExtractionError, SafeZipExtractor
from engines.ingestion.models import ArchiveConfig


def _create_zip_bytes(entries: dict[str, bytes | str]) -> bytes:
    """Helper to create an in-memory zip file from a dictionary of path -> content."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, content in entries.items():
            if isinstance(content, str):
                data = content.encode("utf-8")
            else:
                data = content
            zf.writestr(name, data)
    return buf.getvalue()


def test_extract_valid_zip(tmp_path: Path):
    dest = tmp_path / "extracted_project"
    zip_bytes = _create_zip_bytes({
        "main.py": "print('hello')",
        "pkg/__init__.py": "# pkg",
        "pkg/utils.py": "def helper(): pass\n",
    })

    extractor = SafeZipExtractor()
    result = extractor.extract(zip_bytes, dest)

    assert result.destination_path == dest.resolve()
    assert result.extracted_files_count == 3
    assert (dest / "main.py").read_text() == "print('hello')"
    assert (dest / "pkg" / "__init__.py").read_text() == "# pkg"
    assert (dest / "pkg" / "utils.py").read_text() == "def helper(): pass\n"


def test_extract_malformed_zip_magic_bytes(tmp_path: Path):
    dest = tmp_path / "dest"
    extractor = SafeZipExtractor()

    with pytest.raises(ArchiveExtractionError) as exc_info:
        extractor.extract(b"Not A Zip File Content AT All", dest)
    assert "not a valid ZIP archive" in str(exc_info.value)
    assert not dest.exists()


def test_extract_corrupted_zip_structure(tmp_path: Path):
    dest = tmp_path / "dest"
    # Valid ZIP magic number PK\x03\x04 followed by corrupted junk
    corrupted = b"PK\x03\x04" + b"\x00" * 40
    extractor = SafeZipExtractor()

    with pytest.raises(ArchiveExtractionError):
        extractor.extract(corrupted, dest)
    assert not dest.exists()


def test_zip_slip_traversal_rejected(tmp_path: Path):
    dest = tmp_path / "dest"
    outside_file = tmp_path / "outside.txt"

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("../outside.txt", "evil payload")
    zip_bytes = buf.getvalue()

    extractor = SafeZipExtractor()
    with pytest.raises(ArchiveExtractionError) as exc_info:
        extractor.extract(zip_bytes, dest)

    assert "directory traversal" in str(exc_info.value) or "escapes destination" in str(exc_info.value)
    assert not outside_file.exists()
    assert not dest.exists()


def test_absolute_path_rejected(tmp_path: Path):
    dest = tmp_path / "dest"

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("/root/secret.txt", "evil")
    zip_bytes = buf.getvalue()

    extractor = SafeZipExtractor()
    with pytest.raises(ArchiveExtractionError) as exc_info:
        extractor.extract(zip_bytes, dest)
    assert "absolute path" in str(exc_info.value)
    assert not dest.exists()


def test_windows_drive_specifier_rejected(tmp_path: Path):
    dest = tmp_path / "dest"

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("C:/Windows/win.ini", "evil")
    zip_bytes = buf.getvalue()

    extractor = SafeZipExtractor()
    with pytest.raises(ArchiveExtractionError) as exc_info:
        extractor.extract(zip_bytes, dest)
    assert "drive/stream specifier" in str(exc_info.value)
    assert not dest.exists()


def test_reserved_windows_name_rejected(tmp_path: Path):
    dest = tmp_path / "dest"
    zip_bytes = _create_zip_bytes({
        "src/con.py": "print('reserved')",
    })

    extractor = SafeZipExtractor()
    with pytest.raises(ArchiveExtractionError) as exc_info:
        extractor.extract(zip_bytes, dest)
    assert "reserved device name" in str(exc_info.value)
    assert not dest.exists()


def test_symlink_entry_rejected(tmp_path: Path):
    dest = tmp_path / "dest"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        info = zipfile.ZipInfo("symlink_target")
        # 0o120000 in upper 16 bits specifies a symbolic link in Unix
        info.external_attr = 0o120777 << 16
        zf.writestr(info, "/etc/passwd")
    zip_bytes = buf.getvalue()

    extractor = SafeZipExtractor()
    with pytest.raises(ArchiveExtractionError) as exc_info:
        extractor.extract(zip_bytes, dest)
    assert "symlink or special file" in str(exc_info.value)
    assert not dest.exists()


def test_duplicate_file_paths_rejected(tmp_path: Path):
    dest = tmp_path / "dest"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("file.txt", "first version")
        zf.writestr("file.txt", "second version")
    zip_bytes = buf.getvalue()

    extractor = SafeZipExtractor()
    with pytest.raises(ArchiveExtractionError) as exc_info:
        extractor.extract(zip_bytes, dest)
    assert "duplicate or colliding file path" in str(exc_info.value)
    assert not dest.exists()


def test_case_colliding_file_paths_rejected(tmp_path: Path):
    dest = tmp_path / "dest"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("MyFile.txt", "first")
        zf.writestr("myfile.txt", "second")
    zip_bytes = buf.getvalue()

    extractor = SafeZipExtractor()
    with pytest.raises(ArchiveExtractionError) as exc_info:
        extractor.extract(zip_bytes, dest)
    assert "duplicate or colliding file path" in str(exc_info.value)
    assert not dest.exists()


def test_entry_count_limit_exceeded(tmp_path: Path):
    dest = tmp_path / "dest"
    entries = {f"file_{i}.txt": f"content {i}" for i in range(10)}
    zip_bytes = _create_zip_bytes(entries)

    config = ArchiveConfig(max_file_count=5)
    extractor = SafeZipExtractor(config=config)

    with pytest.raises(ArchiveExtractionError) as exc_info:
        extractor.extract(zip_bytes, dest)
    assert "too many entries" in str(exc_info.value)
    assert not dest.exists()


def test_single_file_size_limit_exceeded(tmp_path: Path):
    dest = tmp_path / "dest"
    zip_bytes = _create_zip_bytes({"big_file.bin": b"x" * 2000})

    config = ArchiveConfig(max_single_file_size_bytes=1000)
    extractor = SafeZipExtractor(config=config)

    with pytest.raises(ArchiveExtractionError) as exc_info:
        extractor.extract(zip_bytes, dest)
    assert "exceeds single file size limit" in str(exc_info.value)
    assert not dest.exists()


def test_total_uncompressed_size_limit_exceeded(tmp_path: Path):
    dest = tmp_path / "dest"
    zip_bytes = _create_zip_bytes({
        "f1.bin": b"a" * 800,
        "f2.bin": b"b" * 800,
    })

    config = ArchiveConfig(max_total_uncompressed_size_bytes=1000)
    extractor = SafeZipExtractor(config=config)

    with pytest.raises(ArchiveExtractionError) as exc_info:
        extractor.extract(zip_bytes, dest)
    assert "maximum total uncompressed size" in str(exc_info.value)
    assert not dest.exists()


def test_suspicious_compression_ratio_zip_bomb(tmp_path: Path):
    dest = tmp_path / "dest"
    # Highly compressible 2MB block of zeros
    zero_data = b"\x00" * (2 * 1024 * 1024)
    zip_bytes = _create_zip_bytes({"bomb.bin": zero_data})

    # Set very strict compression ratio threshold
    config = ArchiveConfig(max_compression_ratio=10.0)
    extractor = SafeZipExtractor(config=config)

    with pytest.raises(ArchiveExtractionError) as exc_info:
        extractor.extract(zip_bytes, dest)
    assert "suspicious compression ratio" in str(exc_info.value)
    assert not dest.exists()


def test_cleanup_on_failure(tmp_path: Path):
    dest = tmp_path / "dest"
    # Archive where second entry triggers traversal error
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("valid_file.txt", "valid")
        zf.writestr("../escape.txt", "evil")
    zip_bytes = buf.getvalue()

    extractor = SafeZipExtractor()
    with pytest.raises(ArchiveExtractionError):
        extractor.extract(zip_bytes, dest)

    # Teardown guarantees dest is removed
    assert not dest.exists()


def test_destination_already_exists_and_not_empty(tmp_path: Path):
    dest = tmp_path / "existing_dir"
    dest.mkdir()
    (dest / "existing_file.txt").write_text("existing")

    zip_bytes = _create_zip_bytes({"new.txt": "hello"})
    extractor = SafeZipExtractor()

    with pytest.raises(ArchiveExtractionError) as exc_info:
        extractor.extract(zip_bytes, dest)
    assert "already exists and is not empty" in str(exc_info.value)
    # Existing content must be intact
    assert (dest / "existing_file.txt").exists()


def test_encrypted_zip_rejected(tmp_path: Path):
    dest = tmp_path / "dest"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("secret.py", b"encrypted-data")
    data = bytearray(buf.getvalue())
    loc = data.find(b"PK\x03\x04")
    if loc != -1:
        data[loc + 6] |= 0x01
    loc_cd = data.find(b"PK\x01\x02")
    if loc_cd != -1:
        data[loc_cd + 8] |= 0x01
    zip_bytes = bytes(data)

    extractor = SafeZipExtractor()
    with pytest.raises(ArchiveExtractionError) as exc_info:
        extractor.extract(zip_bytes, dest)
    assert "encrypted" in str(exc_info.value).lower()
    assert not dest.exists()


def test_unc_path_rejected(tmp_path: Path):
    dest = tmp_path / "dest"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(r"\\remote_server\share\file.txt", "unc")
    zip_bytes = buf.getvalue()

    extractor = SafeZipExtractor()
    with pytest.raises(ArchiveExtractionError):
        extractor.extract(zip_bytes, dest)
    assert not dest.exists()
