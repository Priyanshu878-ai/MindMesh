import io
import os
from pathlib import Path
import shutil
from typing import BinaryIO, Optional, Set, Union
import zipfile

from engines.ingestion.models import ArchiveConfig, ArchiveExtractionResult


class ArchiveExtractionError(Exception):
    """Raised when an archive fails validation, security constraints, or extraction."""
    pass


_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


class SafeZipExtractor:
    """Safely extracts ZIP archives with strict security constraints and resource limits."""

    def __init__(self, config: Optional[ArchiveConfig] = None) -> None:
        self.config = config or ArchiveConfig()

    def extract(
        self,
        archive_source: Union[BinaryIO, Path, str, bytes],
        destination_dir: Path,
    ) -> ArchiveExtractionResult:
        """Extract a ZIP archive into destination_dir safely.

        Security constraints enforced:
        - Validates archive structure and magic bytes (rejects malformed archives).
        - Enforces archive compressed size, entry count, total uncompressed size, and per-file size limits.
        - Defends against zip bombs by enforcing compression ratio thresholds.
        - Defends against Zip Slip by rejecting absolute paths and directory traversal.
        - Rejects symlinks, hardlinks, named pipes, and special device nodes.
        - Rejects duplicate and case-colliding file entries.
        - Decompresses files in streaming chunks with active byte accounting.
        - Atomic directory creation; cleans up partial extraction on any failure.
        - Refuses to overwrite an existing non-empty directory.
        """
        dest = destination_dir.resolve()
        if dest.exists() and any(dest.iterdir()):
            raise ArchiveExtractionError(f"Destination directory already exists and is not empty: '{dest}'")

        file_obj: BinaryIO
        archive_size: int = 0
        should_close = False

        if isinstance(archive_source, (str, Path)):
            archive_path = Path(archive_source)
            if not archive_path.is_file():
                raise ArchiveExtractionError(f"Archive file does not exist: '{archive_path}'")
            archive_size = archive_path.stat().st_size
            if archive_size > self.config.max_archive_size_bytes:
                raise ArchiveExtractionError(
                    f"Archive size exceeds maximum allowed size ({archive_size} > {self.config.max_archive_size_bytes} bytes)"
                )
            file_obj = open(archive_path, "rb")
            should_close = True
        elif isinstance(archive_source, bytes):
            archive_size = len(archive_source)
            if archive_size > self.config.max_archive_size_bytes:
                raise ArchiveExtractionError(
                    f"Archive size exceeds maximum allowed size ({archive_size} > {self.config.max_archive_size_bytes} bytes)"
                )
            file_obj = io.BytesIO(archive_source)
        else:
            file_obj = archive_source
            try:
                cur_pos = file_obj.tell()
                file_obj.seek(0, io.SEEK_END)
                archive_size = file_obj.tell() - cur_pos
                file_obj.seek(cur_pos, io.SEEK_SET)
                if archive_size > self.config.max_archive_size_bytes:
                    raise ArchiveExtractionError(
                        f"Archive size exceeds maximum allowed size ({archive_size} > {self.config.max_archive_size_bytes} bytes)"
                    )
            except (AttributeError, io.UnsupportedOperation):
                archive_size = 0

        created_dest = False
        try:
            if not zipfile.is_zipfile(file_obj):
                raise ArchiveExtractionError("The provided file is not a valid ZIP archive.")

            file_obj.seek(0)
            try:
                zf = zipfile.ZipFile(file_obj, mode="r")
            except (zipfile.BadZipFile, zipfile.LargeZipFile) as exc:
                raise ArchiveExtractionError(f"Malformed ZIP archive: {exc}")

            with zf:
                infolist = zf.infolist()
                if len(infolist) > self.config.max_file_count:
                    raise ArchiveExtractionError(
                        f"Archive contains too many entries ({len(infolist)} > {self.config.max_file_count})"
                    )

                seen_files: Set[str] = set()
                seen_dirs: Set[str] = set()
                total_uncompressed_bytes = 0

                # Pre-validation pass before creating any files on disk
                for info in infolist:
                    filename = info.filename
                    if "\0" in filename:
                        raise ArchiveExtractionError("Archive entry contains illegal null byte in filename.")

                    # Reject encrypted entries
                    if info.flag_bits & 0x1:
                        raise ArchiveExtractionError(
                            f"Archive entry '{filename}' is encrypted. Password-protected archives are not supported."
                        )

                    # Reject absolute paths and drive/stream specifiers
                    if filename.startswith(("/", "\\")):
                        raise ArchiveExtractionError(f"Archive entry contains illegal absolute path: '{filename}'")
                    if ":" in filename:
                        raise ArchiveExtractionError(f"Archive entry contains illegal drive/stream specifier: '{filename}'")
                    if os.path.isabs(filename):
                        raise ArchiveExtractionError(f"Archive entry contains illegal absolute path: '{filename}'")

                    # Normalize path and check directory traversal (Zip Slip)
                    norm = os.path.normpath(filename)
                    drive, _ = os.path.splitdrive(norm)
                    if drive:
                        raise ArchiveExtractionError(f"Archive entry contains illegal drive/UNC specifier: '{filename}'")

                    if norm == ".." or norm.startswith(f"..{os.sep}") or norm.startswith("../") or norm.startswith("..\\"):
                        raise ArchiveExtractionError(f"Archive entry contains directory traversal (Zip Slip): '{filename}'")

                    target_path = (dest / norm).resolve()
                    try:
                        if not (target_path == dest or target_path.is_relative_to(dest)):
                            raise ArchiveExtractionError(f"Archive entry escapes destination directory: '{filename}'")
                    except ValueError:
                        raise ArchiveExtractionError(f"Archive entry escapes destination directory: '{filename}'")

                    # Check for reserved system device names
                    for part in Path(norm).parts:
                        if Path(part).stem.upper() in _RESERVED_NAMES:
                            raise ArchiveExtractionError(f"Archive entry contains reserved device name: '{filename}'")

                    # Reject symlinks and special files (Unix mode in upper 16 bits)
                    mode = info.external_attr >> 16
                    if mode != 0:
                        file_type = mode & 0o170000
                        if file_type in (0o120000, 0o020000, 0o060000, 0o010000, 0o140000):
                            raise ArchiveExtractionError(
                                f"Archive entry '{filename}' is a symlink or special file, which is prohibited."
                            )

                    # Reject duplicate and colliding paths
                    norm_key = norm.replace("\\", "/").rstrip("/").lower()
                    if norm_key and norm_key != ".":
                        if info.is_dir():
                            if norm_key in seen_files:
                                raise ArchiveExtractionError(
                                    f"Archive contains directory colliding with file: '{filename}'"
                                )
                            seen_dirs.add(norm_key)
                        else:
                            if norm_key in seen_files:
                                raise ArchiveExtractionError(
                                    f"Archive contains duplicate or colliding file path: '{filename}'"
                                )
                            if norm_key in seen_dirs:
                                raise ArchiveExtractionError(
                                    f"Archive contains file path colliding with directory: '{filename}'"
                                )
                            seen_files.add(norm_key)

                    # Check uncompressed size limits
                    if info.file_size > self.config.max_single_file_size_bytes:
                        raise ArchiveExtractionError(
                            f"Archive entry '{filename}' exceeds single file size limit ({info.file_size} > {self.config.max_single_file_size_bytes} bytes)"
                        )

                    total_uncompressed_bytes += info.file_size
                    if total_uncompressed_bytes > self.config.max_total_uncompressed_size_bytes:
                        raise ArchiveExtractionError(
                            f"Archive exceeds maximum total uncompressed size ({total_uncompressed_bytes} > {self.config.max_total_uncompressed_size_bytes} bytes)"
                        )

                    # Check suspicious compression ratio (Zip bomb guard)
                    if info.file_size > 1024 * 1024:
                        if info.compress_size == 0:
                            raise ArchiveExtractionError(
                                f"Archive entry '{filename}' has invalid zero compressed size for non-empty file"
                            )
                        ratio = info.file_size / info.compress_size
                        if ratio > self.config.max_compression_ratio:
                            raise ArchiveExtractionError(
                                f"Archive entry '{filename}' has suspicious compression ratio ({ratio:.1f}:1 > {self.config.max_compression_ratio}:1)"
                            )

                if archive_size > 0 and total_uncompressed_bytes > 10 * 1024 * 1024:
                    overall_ratio = total_uncompressed_bytes / archive_size
                    if overall_ratio > self.config.max_compression_ratio:
                        raise ArchiveExtractionError(
                            f"Archive overall compression ratio is suspicious ({overall_ratio:.1f}:1 > {self.config.max_compression_ratio}:1)"
                        )

                # Pre-validation passed: create destination directory
                dest.mkdir(parents=True, exist_ok=True)
                created_dest = True

                extracted_count = 0
                extracted_bytes = 0

                # Extraction pass with streaming chunks
                for info in infolist:
                    norm = os.path.normpath(info.filename)
                    target_path = (dest / norm).resolve()

                    try:
                        if not (target_path == dest or target_path.is_relative_to(dest)):
                            raise ArchiveExtractionError(f"Target path escapes destination: '{norm}'")
                    except ValueError:
                        raise ArchiveExtractionError(f"Target path escapes destination: '{norm}'")

                    if target_path.is_symlink() or any(
                        p.is_symlink() for p in target_path.parents if p != dest and p.is_relative_to(dest)
                    ):
                        raise ArchiveExtractionError(f"Symlink encountered in target path: '{norm}'")

                    if info.is_dir():
                        target_path.mkdir(parents=True, exist_ok=True)
                        continue

                    target_path.parent.mkdir(parents=True, exist_ok=True)
                    file_extracted_bytes = 0

                    with zf.open(info, "r") as src, open(target_path, "wb") as dst:
                        while True:
                            chunk = src.read(65536)
                            if not chunk:
                                break
                            file_extracted_bytes += len(chunk)
                            extracted_bytes += len(chunk)

                            if file_extracted_bytes > info.file_size:
                                raise ArchiveExtractionError(
                                    f"Extracted content of '{info.filename}' exceeded declared file size in archive header"
                                )
                            if file_extracted_bytes > self.config.max_single_file_size_bytes:
                                raise ArchiveExtractionError(
                                    f"Extracted content of '{info.filename}' exceeded single file size limit"
                                )
                            if extracted_bytes > self.config.max_total_uncompressed_size_bytes:
                                raise ArchiveExtractionError(
                                    "Total extracted content exceeded maximum uncompressed size limit"
                                )

                            dst.write(chunk)

                    extracted_count += 1

                return ArchiveExtractionResult(
                    destination_path=dest,
                    extracted_files_count=extracted_count,
                    total_uncompressed_bytes=extracted_bytes,
                )

        except Exception:
            if created_dest and dest.exists():
                shutil.rmtree(dest, ignore_errors=True)
            raise
        finally:
            if should_close:
                try:
                    file_obj.close()
                except Exception:
                    pass
