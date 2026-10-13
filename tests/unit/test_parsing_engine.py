from pathlib import Path
import pytest

from engines.parsing import (
    CodeParser,
    PythonAstParser,
    SymbolKind,
)


def test_python_function_and_parameter_extraction():
    """Verify function, async function, parameters, decorators, docstring, and return type extraction."""
    code = '''
@router.post("/items", response_model=Item)
@auth_required
async def create_item(
    name: str,
    count: int = 1,
    *tags: str,
    debug: bool = False,
    **metadata: Any,
) -> ItemResponse:
    """Create a new item in the database."""
    return ItemResponse(name=name, count=count)
'''
    parser = PythonAstParser()
    result = parser.parse_source(code, file_path="app/api.py")

    assert result.file_path == "app/api.py"
    assert result.language == "Python"
    assert len(result.errors) == 0
    assert len(result.symbols) == 1

    fn = result.symbols[0]
    assert fn.name == "create_item"
    assert fn.kind == SymbolKind.ASYNC_FUNCTION
    assert fn.docstring == "Create a new item in the database."
    assert fn.return_type == "ItemResponse"
    assert "@auth_required" in fn.decorators or any("auth_required" in d for d in fn.decorators)
    assert any("router.post" in d for d in fn.decorators)

    # Verify parameters
    param_names = [p.name for p in fn.parameters]
    assert param_names == ["name", "count", "*tags", "debug", "**metadata"]

    param_map = {p.name: p for p in fn.parameters}
    assert param_map["name"].type_annotation == "str"
    assert param_map["name"].default_value is None

    assert param_map["count"].type_annotation == "int"
    assert param_map["count"].default_value == "1"

    assert param_map["*tags"].type_annotation == "str"

    assert param_map["debug"].type_annotation == "bool"
    assert param_map["debug"].default_value == "False"

    assert param_map["**metadata"].type_annotation == "Any"


def test_python_class_and_method_extraction():
    """Verify class symbol extraction, base classes, methods, and nested functions."""
    code = '''
class UserService(BaseService):
    """Handles user domain operations."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def get_user(self, user_id: str) -> Optional[User]:
        def _validate_id(uid: str) -> bool:
            return len(uid) > 0

        if not _validate_id(user_id):
            return None
        return self.db.find(user_id)
'''
    parser = PythonAstParser()
    result = parser.parse_source(code, file_path="services/user.py")

    assert len(result.errors) == 0
    assert len(result.symbols) == 1

    cls = result.symbols[0]
    assert cls.name == "UserService"
    assert cls.kind == SymbolKind.CLASS
    assert cls.docstring == "Handles user domain operations."
    assert cls.start_line == 2
    assert cls.end_line > cls.start_line

    # Methods
    method_names = [c.name for c in cls.children]
    assert "__init__" in method_names
    assert "get_user" in method_names

    get_user = next(c for c in cls.children if c.name == "get_user")
    assert get_user.kind == SymbolKind.METHOD
    assert get_user.return_type == "Optional[User]"

    # Inner function within get_user
    inner_names = [c.name for c in get_user.children]
    assert "_validate_id" in inner_names
    inner_fn = get_user.children[0]
    assert inner_fn.kind == SymbolKind.FUNCTION


def test_python_import_extraction():
    """Verify extraction of standard, aliased, multi-name, and relative imports."""
    code = '''
import os
import sys as system
from pathlib import Path, PurePath as PP
from . import local_module
from ..parent.module import helper as parent_helper
'''
    parser = PythonAstParser()
    result = parser.parse_source(code, file_path="pkg/sub/mod.py")

    assert len(result.errors) == 0
    assert len(result.imports) == 5

    # 1: import os
    imp1 = result.imports[0]
    assert imp1.module is None
    assert imp1.is_from is False
    assert imp1.level == 0
    assert imp1.names[0].name == "os"
    assert imp1.names[0].alias is None

    # 2: import sys as system
    imp2 = result.imports[1]
    assert imp2.names[0].name == "sys"
    assert imp2.names[0].alias == "system"

    # 3: from pathlib import Path, PurePath as PP
    imp3 = result.imports[2]
    assert imp3.module == "pathlib"
    assert imp3.is_from is True
    assert imp3.level == 0
    assert len(imp3.names) == 2
    assert imp3.names[0].name == "Path"
    assert imp3.names[0].alias is None
    assert imp3.names[1].name == "PurePath"
    assert imp3.names[1].alias == "PP"

    # 4: from . import local_module (relative level 1)
    imp4 = result.imports[3]
    assert imp4.is_from is True
    assert imp4.level == 1
    assert imp4.names[0].name == "local_module"

    # 5: from ..parent.module import helper as parent_helper (relative level 2)
    imp5 = result.imports[4]
    assert imp5.module == "parent.module"
    assert imp5.is_from is True
    assert imp5.level == 2
    assert imp5.names[0].name == "helper"
    assert imp5.names[0].alias == "parent_helper"


def test_cyclomatic_complexity_calculation():
    """Verify cyclomatic complexity score on decision points."""
    code = '''
def complex_algorithm(items: list, threshold: int, flag: bool) -> int:
    score = 0
    if not items or threshold < 0:  # +1 if, +1 bool or
        return 0

    for item in items:              # +1 for
        if item > threshold:        # +1 if
            score += 1
        elif item == 0:             # +1 elif
            continue
        else:
            score -= 1

    while score > 10:               # +1 while
        score -= 2

    try:
        assert score >= 0           # +1 assert
    except ValueError:              # +1 except
        score = 0

    # List comprehension (+1 generator)
    filtered = [x for x in items if x > 0]  # +1 comp generator, +1 comp if

    return score
'''
    parser = PythonAstParser()
    result = parser.parse_source(code, file_path="calc.py")

    assert len(result.symbols) == 1
    fn = result.symbols[0]
    # Base 1 + 1 (if) + 1 (or) + 1 (for) + 1 (if) + 1 (elif) + 1 (while) + 1 (assert) + 1 (except) + 1 (comp) + 1 (comp if) = 11
    assert fn.complexity >= 8


def test_syntax_error_resilience():
    """Verify syntax errors are captured in error records without halting."""
    broken_code = '''
def broken_syntax(x, y:
    return x +
'''
    parser = PythonAstParser()
    result = parser.parse_source(broken_code, file_path="broken.py")

    assert len(result.symbols) == 0
    assert len(result.errors) == 1
    err = result.errors[0]
    assert err.file_path == "broken.py"
    assert err.line_number is not None
    assert "SyntaxError" in err.error_message


def test_empty_and_whitespace_source():
    """Verify empty and whitespace-only files produce clean zero-symbol results."""
    parser = PythonAstParser()
    res1 = parser.parse_source("", file_path="empty.py")
    assert len(res1.symbols) == 0
    assert len(res1.imports) == 0
    assert len(res1.errors) == 0
    assert res1.total_lines == 0

    res2 = parser.parse_source("   \n\n\t  \n", file_path="spaces.py")
    assert len(res2.symbols) == 0
    assert len(res2.errors) == 0


def test_code_parser_facade(tmp_path: Path):
    """Verify CodeParser dispatches Python and non-Python files accurately."""
    py_file = tmp_path / "app.py"
    py_file.write_text("def hello(): pass\n", encoding="utf-8")

    md_file = tmp_path / "README.md"
    md_file.write_text("# Documentation\n\nProject guide.\n", encoding="utf-8")

    parser = CodeParser()

    # Parse Python
    py_res = parser.parse_file(py_file, relative_path="app.py")
    assert py_res.language == "Python"
    assert len(py_res.symbols) == 1
    assert py_res.symbols[0].name == "hello"

    # Parse non-Python Markdown
    md_res = parser.parse_file(md_file, relative_path="README.md")
    assert md_res.language == "Plain Text" or md_res.language == "Markdown"
    assert len(md_res.symbols) == 0
    assert len(md_res.errors) == 0
    assert md_res.total_lines == 3

    # Parse batch files
    batch = parser.parse_files([py_file, md_file], base_root=tmp_path)
    assert len(batch) == 2
    assert batch[0].file_path == "app.py"
    assert batch[1].file_path == "README.md"
