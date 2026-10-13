from pathlib import Path
import re
from typing import List, Optional, Set, Tuple

DEFAULT_IGNORED_DIRS: Set[str] = {
    ".git",
    ".svn",
    ".hg",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    "env",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "dist",
    "build",
    ".next",
    "out",
    "target",
    ".idea",
    ".vscode",
    "vendor",
    ".turbo",
}

DEFAULT_IGNORED_FILES: Set[str] = {
    ".DS_Store",
    "Thumbs.db",
    ".gitmodules",
    ".gitattributes",
}

KNOWN_BINARY_EXTENSIONS: Set[str] = {
    # Executables & libraries
    ".exe",
    ".dll",
    ".so",
    ".dylib",
    ".bin",
    ".wasm",
    ".o",
    ".obj",
    ".a",
    ".lib",
    # Bytecode & compiled
    ".pyc",
    ".pyo",
    ".pyd",
    ".class",
    ".jar",
    ".war",
    # Media
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".ico",
    ".webp",
    ".bmp",
    ".tiff",
    ".mp3",
    ".mp4",
    ".wav",
    ".mov",
    ".avi",
    ".flac",
    ".ogg",
    # Archives
    ".zip",
    ".tar",
    ".gz",
    ".bz2",
    ".xz",
    ".7z",
    ".rar",
    ".tgz",
    ".whl",
    # Documents & fonts
    ".pdf",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".ppt",
    ".pptx",
    ".woff",
    ".woff2",
    ".ttf",
    ".eot",
    ".otf",
    # Databases & big data
    ".db",
    ".sqlite",
    ".sqlite3",
    ".parquet",
    ".arrow",
}

LANGUAGE_BY_EXTENSION: dict[str, str] = {
    ".py": "Python",
    ".pyi": "Python",
    ".js": "JavaScript",
    ".mjs": "JavaScript",
    ".cjs": "JavaScript",
    ".jsx": "JavaScript",
    ".ts": "TypeScript",
    ".mts": "TypeScript",
    ".cts": "TypeScript",
    ".tsx": "TypeScript",
    ".html": "HTML",
    ".htm": "HTML",
    ".css": "CSS",
    ".scss": "CSS",
    ".sass": "CSS",
    ".less": "CSS",
    ".json": "JSON",
    ".jsonc": "JSON",
    ".yaml": "YAML",
    ".yml": "YAML",
    ".md": "Markdown",
    ".markdown": "Markdown",
    ".sql": "SQL",
    ".rs": "Rust",
    ".go": "Go",
    ".java": "Java",
    ".kt": "Kotlin",
    ".kts": "Kotlin",
    ".c": "C",
    ".h": "C",
    ".cpp": "C++",
    ".hpp": "C++",
    ".cc": "C++",
    ".cxx": "C++",
    ".cs": "C#",
    ".rb": "Ruby",
    ".php": "PHP",
    ".sh": "Shell",
    ".bash": "Shell",
    ".zsh": "Shell",
    ".toml": "TOML",
    ".xml": "XML",
    ".vue": "Vue",
    ".svelte": "Svelte",
    ".graphql": "GraphQL",
    ".gql": "GraphQL",
    ".proto": "Protocol Buffer",
    ".r": "R",
    ".swift": "Swift",
    ".scala": "Scala",
    ".dart": "Dart",
    ".lua": "Lua",
}

LANGUAGE_BY_FILENAME: dict[str, str] = {
    "dockerfile": "Dockerfile",
    "containerfile": "Dockerfile",
    "makefile": "Makefile",
    "cmakelists.txt": "CMake",
    "jenkinsfile": "Jenkinsfile",
}


def is_binary_file(file_path: Path, sample_size: int = 8192) -> bool:
    """Check if a file is binary using extension checks and null-byte detection.

    Args:
        file_path: Path to the target file.
        sample_size: Number of initial bytes to examine for null characters.

    Returns:
        True if the file is classified as binary, False if text.
    """
    ext = file_path.suffix.lower()
    if ext in KNOWN_BINARY_EXTENSIONS:
        return True

    try:
        with open(file_path, "rb") as f:
            chunk = f.read(sample_size)
            if b"\x00" in chunk:
                return True
    except OSError:
        # If unreadable, let scanner handle the read failure
        return False

    return False


def detect_language(file_path: Path) -> str:
    """Classify programming language or file format from filename/extension.

    Args:
        file_path: Path to the target file.

    Returns:
        Language name string, or extension-based / 'Plain Text' fallback.
    """
    name_lower = file_path.name.lower()
    if name_lower in LANGUAGE_BY_FILENAME:
        return LANGUAGE_BY_FILENAME[name_lower]

    ext = file_path.suffix.lower()
    if ext in LANGUAGE_BY_EXTENSION:
        return LANGUAGE_BY_EXTENSION[ext]

    if ext:
        return ext.lstrip(".").upper()

    return "Plain Text"


class GitIgnorePattern:
    """Represents a compiled .gitignore pattern with negation and directory constraints."""

    def __init__(self, raw_pattern: str) -> None:
        self.raw_pattern = raw_pattern.strip()
        self.is_negation = self.raw_pattern.startswith("!")
        clean_pat = self.raw_pattern[1:] if self.is_negation else self.raw_pattern

        self.dir_only = clean_pat.endswith("/")
        if self.dir_only:
            clean_pat = clean_pat[:-1]

        self.anchored = clean_pat.startswith("/")
        if self.anchored:
            clean_pat = clean_pat[1:]

        self.regex = self._compile_regex(clean_pat, self.anchored, self.dir_only)

    @staticmethod
    def _compile_regex(pattern: str, anchored: bool, dir_only: bool) -> re.Pattern:
        res = []
        i, n = 0, len(pattern)
        while i < n:
            c = pattern[i]
            if c == "*":
                if i + 1 < n and pattern[i + 1] == "*":
                    if i + 2 < n and pattern[i + 2] == "/":
                        res.append("(?:.+/)?")
                        i += 3
                        continue
                    else:
                        res.append(".*")
                        i += 2
                        continue
                else:
                    res.append("[^/]*")
                    i += 1
            elif c == "?":
                res.append("[^/]")
                i += 1
            elif c in ".[{()\\+^$|":
                res.append("\\" + c)
                i += 1
            else:
                res.append(c)
                i += 1

        pattern_regex = "".join(res)
        if anchored or "/" in pattern:
            full = f"^{pattern_regex}" + ("(?:/.*)?$" if dir_only else "$")
        else:
            full = f"(?:^|.*/){pattern_regex}" + ("(?:/.*)?$" if dir_only else "$")

        return re.compile(full, re.IGNORECASE)

    def matches(self, rel_path: str, is_dir: bool) -> bool:
        """Check if relative POSIX path matches this pattern."""
        if self.dir_only and not is_dir:
            # If pattern requires a directory, but target is a file,
            # match only if rel_path is inside a matching directory component
            return bool(self.regex.match(rel_path + "/"))

        return bool(self.regex.match(rel_path))


class GitIgnoreFilter:
    """Evaluates relative file and directory paths against loaded .gitignore rules.

    Limitations:
    - Patterns with character range escapes like `\\[` are simplified.
    - Path evaluation operates from repository root.
    """

    def __init__(self, patterns: Optional[List[str]] = None) -> None:
        self.rules: List[GitIgnorePattern] = []
        if patterns:
            for p in patterns:
                self.add_pattern(p)

    def add_pattern(self, line: str) -> None:
        """Parse and add a single pattern line if non-empty and non-comment."""
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            return
        self.rules.append(GitIgnorePattern(stripped))

    @classmethod
    def load_from_file(cls, gitignore_path: Path) -> "GitIgnoreFilter":
        """Factory method to load rules from a .gitignore file if it exists."""
        instance = cls()
        if gitignore_path.is_file():
            try:
                with open(gitignore_path, "r", encoding="utf-8", errors="replace") as f:
                    for line in f:
                        instance.add_pattern(line)
            except OSError:
                pass
        return instance

    def is_ignored(self, rel_posix_path: str, is_dir: bool = False) -> bool:
        """Evaluate path against rules in sequence. Negation (!pattern) can unignore paths."""
        ignored = False
        for rule in self.rules:
            if rule.matches(rel_posix_path, is_dir):
                ignored = not rule.is_negation
        return ignored
