from pathlib import Path
from typing import List, Optional

from engines.parsing.models import (
    ParseErrorRecord,
    ParsedFileResult,
)
from engines.parsing.python import PythonAstParser


class CodeParser:
    """Unified entry point for multi-language AST code intelligence."""

    def __init__(self) -> None:
        self.python_parser = PythonAstParser()

    def parse_source(
        self,
        code: str,
        language: str = "Python",
        file_path: str = "",
    ) -> ParsedFileResult:
        """Parse source code string based on detected or supplied language."""
        lang_lower = language.lower() if language else ""
        ext_lower = Path(file_path).suffix.lower() if file_path else ""

        if lang_lower == "python" or ext_lower in {".py", ".pyi"}:
            return self.python_parser.parse_source(code, file_path=file_path)

        # Non-Python or plain text files return empty symbols/imports cleanly
        return ParsedFileResult(
            file_path=file_path,
            language=language or "Plain Text",
            symbols=[],
            imports=[],
            errors=[],
            total_lines=len(code.splitlines()),
        )

    def parse_file(
        self,
        file_path: Path | str,
        language: Optional[str] = None,
        relative_path: Optional[str] = None,
    ) -> ParsedFileResult:
        """Read and parse a file from disk with safe encoding fallback."""
        path_obj = Path(file_path)
        display_path = relative_path or path_obj.as_posix()

        if not path_obj.exists():
            return ParsedFileResult(
                file_path=display_path,
                language=language or "Unknown",
                symbols=[],
                imports=[],
                errors=[
                    ParseErrorRecord(
                        file_path=display_path,
                        line_number=None,
                        error_message="File does not exist",
                    )
                ],
                total_lines=0,
            )

        try:
            with open(path_obj, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
        except OSError as err:
            return ParsedFileResult(
                file_path=display_path,
                language=language or "Unknown",
                symbols=[],
                imports=[],
                errors=[
                    ParseErrorRecord(
                        file_path=display_path,
                        line_number=None,
                        error_message=f"Read failure: {str(err)}",
                    )
                ],
                total_lines=0,
            )

        # Detect language if omitted
        detected_lang = language
        if not detected_lang:
            detected_lang = "Python" if path_obj.suffix.lower() in {".py", ".pyi"} else "Plain Text"

        return self.parse_source(content, language=detected_lang, file_path=display_path)

    def parse_files(
        self,
        file_paths: List[Path | str],
        base_root: Optional[Path | str] = None,
    ) -> List[ParsedFileResult]:
        """Parse multiple files, normalizing paths relative to base_root when specified."""
        results: List[ParsedFileResult] = []
        root_path = Path(base_root).resolve() if base_root else None

        for fp in file_paths:
            path_obj = Path(fp).resolve()
            if root_path and path_obj.is_relative_to(root_path):
                rel_posix = path_obj.relative_to(root_path).as_posix()
            else:
                rel_posix = path_obj.as_posix()

            results.append(self.parse_file(path_obj, relative_path=rel_posix))

        return results
