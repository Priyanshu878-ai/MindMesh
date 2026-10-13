import ast
from typing import Any, List, Optional, Tuple

from engines.parsing.models import (
    CodeSymbol,
    ImportItem,
    ImportStatement,
    ParameterInfo,
    ParseErrorRecord,
    ParsedFileResult,
    SymbolKind,
)


def _safe_unparse(node: Optional[ast.AST]) -> Optional[str]:
    """Safely convert an AST expression node to its string representation."""
    if node is None:
        return None
    try:
        return ast.unparse(node)
    except Exception:
        return None


def calculate_cyclomatic_complexity(node: ast.AST) -> int:
    """Calculate cyclomatic complexity for a function or method AST node.

    Counts decision points: if, while, for, except, assert, boolean operators,
    and comprehension loops, without recursing into nested function definitions.
    """
    complexity = 1

    def _traverse(n: ast.AST) -> None:
        nonlocal complexity
        for child in ast.iter_child_nodes(n):
            # Skip nested functions/classes to avoid conflating child complexity
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue

            if isinstance(child, (ast.If, ast.IfExp, ast.For, ast.AsyncFor, ast.While, ast.ExceptHandler, ast.Assert)):
                complexity += 1
            elif isinstance(child, ast.BoolOp):
                complexity += max(0, len(child.values) - 1)
            elif isinstance(child, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
                complexity += len(child.generators)

            _traverse(child)

    _traverse(node)
    return complexity


def _extract_parameters(args_node: ast.arguments) -> List[ParameterInfo]:
    """Extract positional, keyword, vararg, and kwarg parameters with defaults and annotations."""
    parameters: List[ParameterInfo] = []

    # Map positional defaults (aligned to the right)
    pos_args = list(args_node.posonlyargs) + list(args_node.args)
    defaults = list(args_node.defaults)
    num_non_defaults = len(pos_args) - len(defaults)

    for i, arg in enumerate(pos_args):
        annotation = _safe_unparse(arg.annotation)
        default_val = None
        if i >= num_non_defaults:
            default_idx = i - num_non_defaults
            default_val = _safe_unparse(defaults[default_idx])

        parameters.append(
            ParameterInfo(
                name=arg.arg,
                type_annotation=annotation,
                default_value=default_val,
            )
        )

    # Vararg (*args)
    if args_node.vararg:
        parameters.append(
            ParameterInfo(
                name=f"*{args_node.vararg.arg}",
                type_annotation=_safe_unparse(args_node.vararg.annotation),
                default_value=None,
            )
        )

    # Keyword-only arguments
    for arg, default in zip(args_node.kwonlyargs, args_node.kw_defaults):
        parameters.append(
            ParameterInfo(
                name=arg.arg,
                type_annotation=_safe_unparse(arg.annotation),
                default_value=_safe_unparse(default),
            )
        )

    # Kwarg (**kwargs)
    if args_node.kwarg:
        parameters.append(
            ParameterInfo(
                name=f"**{args_node.kwarg.arg}",
                type_annotation=_safe_unparse(args_node.kwarg.annotation),
                default_value=None,
            )
        )

    return parameters


class PythonAstParser:
    """Extracts symbols, metrics, and import dependency records from Python source code."""

    def parse_source(self, code: str, file_path: str = "") -> ParsedFileResult:
        """Parse Python source code string into a structured ParsedFileResult.

        Handles syntax errors, empty inputs, and docstrings gracefully.
        """
        lines = code.splitlines()
        total_lines = len(lines)

        if not code.strip():
            return ParsedFileResult(
                file_path=file_path,
                language="Python",
                symbols=[],
                imports=[],
                errors=[],
                total_lines=total_lines,
            )

        try:
            tree = ast.parse(code, filename=file_path)
        except SyntaxError as err:
            return ParsedFileResult(
                file_path=file_path,
                language="Python",
                symbols=[],
                imports=[],
                errors=[
                    ParseErrorRecord(
                        file_path=file_path,
                        line_number=err.lineno,
                        error_message=f"SyntaxError: {err.msg}",
                    )
                ],
                total_lines=total_lines,
            )
        except Exception as err:
            return ParsedFileResult(
                file_path=file_path,
                language="Python",
                symbols=[],
                imports=[],
                errors=[
                    ParseErrorRecord(
                        file_path=file_path,
                        line_number=None,
                        error_message=f"Parse failure: {str(err)}",
                    )
                ],
                total_lines=total_lines,
            )

        imports: List[ImportStatement] = []
        symbols: List[CodeSymbol] = []

        for node in tree.body:
            if isinstance(node, ast.Import):
                imports.append(
                    ImportStatement(
                        module=None,
                        names=[ImportItem(name=alias.name, alias=alias.asname) for alias in node.names],
                        is_from=False,
                        level=0,
                        line_number=node.lineno,
                    )
                )
            elif isinstance(node, ast.ImportFrom):
                imports.append(
                    ImportStatement(
                        module=node.module,
                        names=[ImportItem(name=alias.name, alias=alias.asname) for alias in node.names],
                        is_from=True,
                        level=node.level,
                        line_number=node.lineno,
                    )
                )
            elif isinstance(node, ast.ClassDef):
                symbols.append(self._extract_class(node))
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                symbols.append(self._extract_function(node, in_class=False))

        return ParsedFileResult(
            file_path=file_path,
            language="Python",
            symbols=symbols,
            imports=imports,
            errors=[],
            total_lines=total_lines,
        )

    def _extract_class(self, node: ast.ClassDef) -> CodeSymbol:
        """Extract a class symbol and its methods/inner functions recursively."""
        docstring = ast.get_docstring(node)
        decorators = [_safe_unparse(d) for d in node.decorator_list if _safe_unparse(d)]
        start_line = node.lineno
        end_line = getattr(node, "end_lineno", node.lineno)

        children: List[CodeSymbol] = []
        for item in node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                children.append(self._extract_function(item, in_class=True))
            elif isinstance(item, ast.ClassDef):
                children.append(self._extract_class(item))

        return CodeSymbol(
            name=node.name,
            kind=SymbolKind.CLASS,
            start_line=start_line,
            end_line=end_line,
            docstring=docstring,
            decorators=decorators,
            parameters=[],
            return_type=None,
            complexity=1,
            children=children,
        )

    def _extract_function(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        in_class: bool,
    ) -> CodeSymbol:
        """Extract a function or method symbol with parameters, return types, and complexity."""
        if in_class:
            kind = SymbolKind.METHOD
        elif isinstance(node, ast.AsyncFunctionDef):
            kind = SymbolKind.ASYNC_FUNCTION
        else:
            kind = SymbolKind.FUNCTION

        docstring = ast.get_docstring(node)
        decorators = [_safe_unparse(d) for d in node.decorator_list if _safe_unparse(d)]
        start_line = node.lineno
        end_line = getattr(node, "end_lineno", node.lineno)
        parameters = _extract_parameters(node.args)
        return_type = _safe_unparse(node.returns)
        complexity = calculate_cyclomatic_complexity(node)

        # Extract nested inner functions or inner classes
        children: List[CodeSymbol] = []
        for item in node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                children.append(self._extract_function(item, in_class=False))
            elif isinstance(item, ast.ClassDef):
                children.append(self._extract_class(item))

        return CodeSymbol(
            name=node.name,
            kind=kind,
            start_line=start_line,
            end_line=end_line,
            docstring=docstring,
            decorators=decorators,
            parameters=parameters,
            return_type=return_type,
            complexity=complexity,
            children=children,
        )
