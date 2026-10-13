import ast
import re
from typing import Any, Dict, List, Optional, Set, Tuple

from engines.analysis.models import EntryPoint, EntryPointType
from engines.parsing.models import CodeSymbol, ParsedFileResult

HTTP_METHODS: Set[str] = {
    "get",
    "post",
    "put",
    "delete",
    "patch",
    "options",
    "head",
}

ROUTE_ATTRS: Set[str] = HTTP_METHODS | {"route", "api_route"}


def parse_route_decorator(decorator_str: str) -> Optional[Tuple[str, str, Dict[str, Any]]]:
    """Parse a route decorator string and extract HTTP method, route path, and metadata.

    Supports FastAPI (@router.get, @app.post, etc.) and Flask (@app.route, @bp.route, etc.).
    Returns (http_method, route_path, metadata) or None if not a recognized route decorator.
    """
    clean_str = decorator_str.strip()
    if clean_str.startswith("@"):
        clean_str = clean_str[1:].strip()

    # Strategy 1: AST expression parsing
    try:
        expr_ast = ast.parse(clean_str, mode="eval")
        if isinstance(expr_ast.body, ast.Call):
            call_node = expr_ast.body
            func_node = call_node.func

            if isinstance(func_node, ast.Attribute):
                attr_name = func_node.attr.lower()

                if attr_name in ROUTE_ATTRS:
                    # Extract route path from first positional arg or 'path' / 'rule' kwarg
                    route_path = "/"
                    if call_node.args and isinstance(call_node.args[0], ast.Constant):
                        route_path = str(call_node.args[0].value)
                    else:
                        for kw in call_node.keywords:
                            if kw.arg in ("path", "rule") and isinstance(kw.value, ast.Constant):
                                route_path = str(kw.value.value)
                                break

                    # Determine HTTP method(s)
                    if attr_name in HTTP_METHODS:
                        http_method = attr_name.upper()
                        methods_list = [http_method]
                    else:
                        # .route or .api_route: inspect 'methods' keyword argument
                        methods_list = ["GET"]
                        for kw in call_node.keywords:
                            if kw.arg == "methods":
                                extracted = _extract_string_list_from_ast(kw.value)
                                if extracted:
                                    methods_list = [m.upper() for m in extracted]
                                break
                        http_method = methods_list[0] if methods_list else "GET"

                    metadata: Dict[str, Any] = {
                        "decorator": decorator_str,
                        "methods": methods_list,
                    }
                    return http_method, route_path, metadata
    except Exception:
        pass

    # Strategy 2: Regex fallback
    match = re.search(
        r"(?:@?[\w\.]+\.)(get|post|put|delete|patch|options|head|route|api_route)\s*\(\s*([\"'])(.*?)\2",
        clean_str,
        re.IGNORECASE,
    )
    if match:
        attr_name = match.group(1).lower()
        route_path = match.group(3)

        if attr_name in HTTP_METHODS:
            http_method = attr_name.upper()
            methods_list = [http_method]
        else:
            # Check methods in regex
            methods_match = re.search(r"methods\s*=\s*\[(.*?)\]", clean_str, re.IGNORECASE)
            if methods_match:
                methods_list = [
                    m.strip(" '\"").upper()
                    for m in methods_match.group(1).split(",")
                    if m.strip(" '\"")
                ]
            else:
                methods_list = ["GET"]
            http_method = methods_list[0] if methods_list else "GET"

        metadata = {
            "decorator": decorator_str,
            "methods": methods_list,
        }
        return http_method, route_path, metadata

    return None


def _extract_string_list_from_ast(node: ast.AST) -> List[str]:
    """Helper to extract list or tuple of string literals from AST."""
    if isinstance(node, (ast.List, ast.Tuple)):
        items = []
        for elt in node.elts:
            if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                items.append(elt.value)
        return items
    elif isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    return []


def is_name_main_block(node: ast.If) -> bool:
    """Check if an ast.If node represents an 'if __name__ == "__main__":' guard."""
    test = node.test
    if isinstance(test, ast.Compare):
        # Left == Right: __name__ == '__main__' or '__main__' == __name__
        left = test.left
        ops = test.ops
        comparators = test.comparators

        has_eq = any(isinstance(op, ast.Eq) for op in ops)
        if not has_eq or not comparators:
            return False

        right = comparators[0]

        # Case 1: __name__ == '__main__'
        if (
            isinstance(left, ast.Name)
            and left.id == "__name__"
            and isinstance(right, ast.Constant)
            and right.value == "__main__"
        ):
            return True

        # Case 2: '__main__' == __name__
        if (
            isinstance(left, ast.Constant)
            and left.value == "__main__"
            and isinstance(right, ast.Name)
            and right.id == "__name__"
        ):
            return True

    return False


class EntryPointDetector:
    """Detects application entrypoints such as HTTP routes and CLI entry blocks."""

    def detect_from_code(self, code: str, file_path: str = "") -> List[EntryPoint]:
        """Detect all entrypoints (routes and CLI blocks) from raw Python source code."""
        entry_points: List[EntryPoint] = []
        if not code.strip():
            return entry_points

        try:
            tree = ast.parse(code, filename=file_path)
        except Exception:
            return entry_points

        # 1. Detect if __name__ == '__main__': blocks at module level
        for node in tree.body:
            if isinstance(node, ast.If) and is_name_main_block(node):
                entry_points.append(
                    EntryPoint(
                        id=f"entrypoint:{file_path}:__main__",
                        name="__main__",
                        file_path=file_path,
                        line_number=node.lineno,
                        entry_type=EntryPointType.CLI_SCRIPT,
                        symbol_id=f"symbol:{file_path}:__main__",
                        metadata={
                            "block": "if __name__ == '__main__':",
                            "start_line": node.lineno,
                            "end_line": getattr(node, "end_lineno", node.lineno),
                        },
                    )
                )

        # 2. Traverse AST to find decorated functions or methods with scope awareness
        def _scan_items(items: List[ast.AST], parent_class: Optional[str] = None) -> None:
            for item in items:
                if isinstance(item, ast.ClassDef):
                    _scan_items(item.body, parent_class=item.name)
                elif isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    scoped_name = f"{parent_class}.{item.name}" if parent_class else item.name
                    symbol_id = f"symbol:{file_path}:{scoped_name}"
                    for dec_node in item.decorator_list:
                        try:
                            dec_str = ast.unparse(dec_node)
                        except Exception:
                            continue

                        parsed = parse_route_decorator(dec_str)
                        if parsed:
                            http_method, route_path, metadata = parsed
                            entry_id = f"entrypoint:{file_path}:{http_method}:{route_path}"
                            entry_points.append(
                                EntryPoint(
                                    id=entry_id,
                                    name=scoped_name,
                                    file_path=file_path,
                                    line_number=item.lineno,
                                    entry_type=EntryPointType.HTTP_ROUTE,
                                    symbol_id=symbol_id,
                                    route_path=route_path,
                                    http_method=http_method,
                                    metadata=metadata,
                                )
                            )
                    _scan_items(item.body, parent_class=scoped_name)

        _scan_items(tree.body)
        return entry_points

    def detect_from_parsed_file(
        self,
        parsed_file: ParsedFileResult,
        code: Optional[str] = None,
    ) -> List[EntryPoint]:
        """Detect entry points from a ParsedFileResult, optionally inspecting code for CLI blocks."""
        entry_points: List[EntryPoint] = []
        file_path = parsed_file.file_path

        # 1. Route entry points from extracted symbols and decorators
        def _check_symbol(sym: CodeSymbol, scope_prefix: str = "") -> None:
            scoped_name = f"{scope_prefix}.{sym.name}" if scope_prefix else sym.name
            symbol_id = f"symbol:{file_path}:{scoped_name}"

            for dec in sym.decorators:
                parsed = parse_route_decorator(dec)
                if parsed:
                    http_method, route_path, metadata = parsed
                    entry_id = f"entrypoint:{file_path}:{http_method}:{route_path}"
                    entry_points.append(
                        EntryPoint(
                            id=entry_id,
                            name=sym.name,
                            file_path=file_path,
                            line_number=sym.start_line,
                            entry_type=EntryPointType.HTTP_ROUTE,
                            symbol_id=symbol_id,
                            route_path=route_path,
                            http_method=http_method,
                            metadata=metadata,
                        )
                    )

            for child in sym.children:
                _check_symbol(child, scope_prefix=scoped_name)

        for s in parsed_file.symbols:
            _check_symbol(s)

        # 2. If code is available, detect CLI blocks
        if code:
            try:
                tree = ast.parse(code, filename=file_path)
                for node in tree.body:
                    if isinstance(node, ast.If) and is_name_main_block(node):
                        entry_points.append(
                            EntryPoint(
                                id=f"entrypoint:{file_path}:__main__",
                                name="__main__",
                                file_path=file_path,
                                line_number=node.lineno,
                                entry_type=EntryPointType.CLI_SCRIPT,
                                symbol_id=f"symbol:{file_path}:__main__",
                                metadata={
                                    "block": "if __name__ == '__main__':",
                                    "start_line": node.lineno,
                                    "end_line": getattr(node, "end_lineno", node.lineno),
                                },
                            )
                        )
            except Exception:
                pass

        return entry_points

    def detect_all(
        self,
        parsed_files: List[ParsedFileResult],
        source_codes: Optional[Dict[str, str]] = None,
    ) -> List[EntryPoint]:
        """Detect entry points across all parsed files in a project."""
        codes = source_codes or {}
        all_entry_points: List[EntryPoint] = []
        for pf in parsed_files:
            code = codes.get(pf.file_path)
            all_entry_points.extend(self.detect_from_parsed_file(pf, code=code))
        return all_entry_points
