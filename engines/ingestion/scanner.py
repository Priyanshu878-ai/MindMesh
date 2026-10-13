from collections import deque
import hashlib
import os
from pathlib import Path
import time
from typing import Dict, List, Set

from engines.ingestion.filters import (
    DEFAULT_IGNORED_DIRS,
    DEFAULT_IGNORED_FILES,
    GitIgnoreFilter,
    detect_language,
    is_binary_file,
)
from engines.ingestion.models import (
    FileDescriptor,
    IngestionConfig,
    IngestionSummary,
    SkippedFile,
)


class CodebaseScanner:
    """Deterministic, secure filesystem scanner for repository code ingestion."""

    def __init__(self, config: IngestionConfig | None = None) -> None:
        self.config = config or IngestionConfig()

    def scan(self, root_path: Path | str) -> IngestionSummary:
        """Scan target codebase directory and produce catalog of source files.

        Args:
            root_path: Directory path to scan.

        Returns:
            IngestionSummary containing cataloged files, metrics, and skip records.

        Raises:
            FileNotFoundError: If root directory does not exist.
            NotADirectoryError: If root path is not a directory.
        """
        start_time = time.perf_counter()

        canonical_root = Path(root_path).resolve()
        if not canonical_root.exists():
            raise FileNotFoundError(f"Directory not found: {root_path}")
        if not canonical_root.is_dir():
            raise NotADirectoryError(f"Target path is not a directory: {root_path}")

        gitignore = GitIgnoreFilter.load_from_file(canonical_root / ".gitignore")
        for custom_pat in self.config.custom_ignore_patterns:
            gitignore.add_pattern(custom_pat)

        files: List[FileDescriptor] = []
        skipped_files: List[SkippedFile] = []
        languages: Dict[str, int] = {}
        total_size_bytes = 0
        total_lines = 0
        total_code_lines = 0
        total_blank_lines = 0
        scanned_files_count = 0
        is_truncated = False

        # Directory loop and traversal tracking
        visited_dirs: Set[Path] = {canonical_root}
        dir_queue: deque[Path] = deque([canonical_root])

        while dir_queue:
            current_dir = dir_queue.popleft()

            try:
                # Deterministic sorting by lower-case name for repeatability across platforms
                entries = sorted(os.scandir(current_dir), key=lambda e: e.name.lower())
            except OSError:
                continue

            subdirs: List[Path] = []
            file_entries = []

            for entry in entries:
                try:
                    entry_path = Path(entry.path)
                    is_symlink = entry.is_symlink()

                    # Handle directories
                    if entry.is_dir(follow_symlinks=self.config.follow_symlinks):
                        rel_dir_posix = entry_path.relative_to(canonical_root).as_posix()

                        # Check default ignores and gitignore for directory
                        if entry.name in DEFAULT_IGNORED_DIRS:
                            continue
                        if gitignore.is_ignored(rel_dir_posix, is_dir=True):
                            continue

                        # Symlink safety check for directories
                        if is_symlink:
                            if not self.config.follow_symlinks:
                                continue
                            try:
                                resolved_target = entry_path.resolve()
                                if (
                                    not resolved_target.is_relative_to(canonical_root)
                                    or resolved_target in visited_dirs
                                ):
                                    continue
                                visited_dirs.add(resolved_target)
                            except OSError:
                                continue
                        else:
                            visited_dirs.add(entry_path.resolve())

                        subdirs.append(entry_path)

                    elif entry.is_file(follow_symlinks=self.config.follow_symlinks):
                        file_entries.append((entry, entry_path, is_symlink))

                except OSError:
                    continue

            # Queue valid subdirectories
            dir_queue.extend(subdirs)

            # Process files in current directory
            for entry, entry_path, is_symlink in file_entries:
                scanned_files_count += 1
                rel_posix = entry_path.relative_to(canonical_root).as_posix()

                # Check scan limit threshold
                if len(files) >= self.config.max_total_files:
                    is_truncated = True
                    break

                # Symlink boundary check
                if is_symlink:
                    try:
                        resolved_target = entry_path.resolve()
                        if not resolved_target.is_relative_to(canonical_root):
                            skipped_files.append(
                                SkippedFile(path=rel_posix, reason="symlink_outside_root")
                            )
                            continue
                    except OSError:
                        skipped_files.append(
                            SkippedFile(path=rel_posix, reason="unreadable")
                        )
                        continue

                # Default file ignores (e.g., .DS_Store, Thumbs.db)
                if entry.name in DEFAULT_IGNORED_FILES:
                    skipped_files.append(
                        SkippedFile(path=rel_posix, reason="ignored")
                    )
                    continue

                # Gitignore filtering
                if gitignore.is_ignored(rel_posix, is_dir=False):
                    skipped_files.append(
                        SkippedFile(path=rel_posix, reason="ignored")
                    )
                    continue

                # Stat file safely (handling race conditions)
                try:
                    st = entry.stat(follow_symlinks=self.config.follow_symlinks)
                    file_size = st.st_size
                except OSError:
                    skipped_files.append(
                        SkippedFile(path=rel_posix, reason="unreadable")
                    )
                    continue

                # Size constraint check (5 MiB default limit)
                if file_size > self.config.max_file_size_bytes:
                    skipped_files.append(
                        SkippedFile(path=rel_posix, reason="file_too_large")
                    )
                    continue

                # Binary classification
                if is_binary_file(entry_path):
                    skipped_files.append(
                        SkippedFile(path=rel_posix, reason="binary")
                    )
                    continue

                # Content reading & hashing
                try:
                    with open(entry_path, "rb") as f:
                        raw_bytes = f.read()
                except OSError:
                    skipped_files.append(
                        SkippedFile(path=rel_posix, reason="unreadable")
                    )
                    continue

                sha256 = hashlib.sha256(raw_bytes).hexdigest()

                # Line metrics semantics
                if not raw_bytes:
                    f_total_lines = 0
                    f_code_lines = 0
                    f_blank_lines = 0
                else:
                    # Decode safely with replacement character for non-UTF8 sequences
                    text_content = raw_bytes.decode("utf-8", errors="replace")
                    lines = text_content.splitlines()
                    f_total_lines = len(lines)
                    f_blank_lines = sum(1 for line in lines if not line.strip())
                    f_code_lines = f_total_lines - f_blank_lines

                lang = detect_language(entry_path)

                descriptor = FileDescriptor(
                    path=rel_posix,
                    name=entry.name,
                    extension=entry_path.suffix.lower(),
                    language=lang,
                    size_bytes=file_size,
                    total_lines=f_total_lines,
                    code_lines=f_code_lines,
                    blank_lines=f_blank_lines,
                    sha256=sha256,
                )

                files.append(descriptor)
                languages[lang] = languages.get(lang, 0) + 1
                total_size_bytes += file_size
                total_lines += f_total_lines
                total_code_lines += f_code_lines
                total_blank_lines += f_blank_lines

            if is_truncated:
                break

        duration_ms = (time.perf_counter() - start_time) * 1000.0

        return IngestionSummary(
            project_root=str(canonical_root),
            scanned_files_count=scanned_files_count,
            included_files_count=len(files),
            skipped_files_count=len(skipped_files),
            total_size_bytes=total_size_bytes,
            total_lines=total_lines,
            total_code_lines=total_code_lines,
            total_blank_lines=total_blank_lines,
            is_truncated=is_truncated,
            languages=languages,
            files=files,
            skipped_files=skipped_files,
            duration_ms=round(duration_ms, 2),
        )
