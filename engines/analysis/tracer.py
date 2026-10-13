import ast
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from engines.analysis.entrypoints import EntryPointDetector
from engines.analysis.models import (
    EntryPoint,
    EntryPointType,
    ExecutionTrace,
    TraceMetrics,
    TraceStep,
    TraceTree,
)
from engines.graph.models import DependencyGraph, EdgeType
from engines.parsing.models import CodeSymbol, ParsedFileResult


class ExecutionTracer:
    """Performs deterministic execution path tracing, branching analysis, and pathfinding."""

    def __init__(
        self,
        graph: Optional[DependencyGraph] = None,
        parsed_files: Optional[List[ParsedFileResult]] = None,
        source_codes: Optional[Dict[str, str]] = None,
        entry_points: Optional[List[EntryPoint]] = None,
    ) -> None:
        self._adjacency: Dict[str, List[TraceStep]] = defaultdict(list)
        self._known_nodes: Dict[str, Dict[str, Any]] = {}
        self.entry_points: List[EntryPoint] = entry_points or []

        # 1. Index symbols from parsed files
        self._symbol_index: Dict[str, Dict[str, str]] = defaultdict(dict)
        self._imports_by_file: Dict[str, List] = {}
        self._module_to_file: Dict[str, str] = {}

        if parsed_files:
            self._index_parsed_files(parsed_files)

        # 2. Extract call edges from source codes if available
        if source_codes:
            self._extract_calls_from_source(source_codes, parsed_files or [])

        # 3. Incorporate edges from DependencyGraph if provided
        if graph:
            self._load_from_graph(graph)

        # 4. Connect entrypoints to their handler symbols
        if self.entry_points:
            self._connect_entry_points(self.entry_points)

    def add_call_edge(
        self,
        source_id: str,
        target_id: str,
        call_type: str = "direct_call",
        line_number: Optional[int] = None,
        file_path: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Register a directed call step from source to target."""
        step = TraceStep(
            step_index=0,
            source_id=source_id,
            target_id=target_id,
            call_type=call_type,
            file_path=file_path,
            line_number=line_number,
            metadata=metadata or {},
        )
        self._adjacency[source_id].append(step)

    def trace_execution(
        self,
        entry_point: Union[EntryPoint, str],
        max_depth: int = 15,
    ) -> ExecutionTrace:
        """Trace deterministic call hierarchy starting from an EntryPoint or symbol ID.

        Enforces recursion and cycle protection, records branch order deterministically,
        and halts traversal when max_depth is reached.
        """
        if isinstance(entry_point, EntryPoint):
            start_id = entry_point.id
            root_name = entry_point.name
            ep_obj = entry_point
        else:
            start_id = entry_point
            root_name = entry_point.split(":")[-1]
            ep_obj = EntryPoint(
                id=start_id,
                name=root_name,
                file_path=self._extract_file_from_id(start_id) or "",
                line_number=1,
                entry_type=EntryPointType.GENERIC,
            )

        steps: List[TraceStep] = []
        has_cycles = False
        active_path: Set[str] = set()

        def _traverse(current_id: str, current_name: str, depth: int) -> TraceTree:
            nonlocal has_cycles

            tree_node = TraceTree(
                node_id=current_id,
                name=current_name,
                depth=depth,
                children=[],
            )

            # 1. Max depth enforcement: halt if current node has reached max_depth
            if depth >= max_depth:
                if self._adjacency.get(current_id):
                    tree_node.metadata["depth_limited"] = True
                return tree_node

            active_path.add(current_id)

            # Sort outgoing edges deterministically by line_number, target_id, call_type
            outgoing = sorted(
                self._adjacency.get(current_id, []),
                key=lambda s: (s.line_number or 0, s.target_id, s.call_type),
            )

            for step_template in outgoing:
                target_id = step_template.target_id
                target_name = target_id.split(":")[-1]

                # 2. Cycle detection on active call stack
                if target_id in active_path:
                    has_cycles = True
                    cycle_step = TraceStep(
                        step_index=len(steps),
                        source_id=current_id,
                        target_id=target_id,
                        call_type=step_template.call_type,
                        file_path=step_template.file_path,
                        line_number=step_template.line_number,
                        metadata={**step_template.metadata, "is_cycle": True},
                    )
                    steps.append(cycle_step)
                    tree_node.children.append(
                        TraceTree(
                            node_id=target_id,
                            name=target_name,
                            depth=depth + 1,
                            metadata={"is_cycle": True},
                        )
                    )
                    continue

                # 3. Normal step and recursion
                step = TraceStep(
                    step_index=len(steps),
                    source_id=current_id,
                    target_id=target_id,
                    call_type=step_template.call_type,
                    file_path=step_template.file_path,
                    line_number=step_template.line_number,
                    metadata=dict(step_template.metadata),
                )
                steps.append(step)

                child_tree = _traverse(target_id, target_name, depth + 1)
                tree_node.children.append(child_tree)

            active_path.remove(current_id)
            return tree_node

        root_tree = _traverse(start_id, root_name, 0)
        metrics = self._calculate_metrics(ep_obj, steps, root_tree, has_cycles)

        return ExecutionTrace(
            entry_point=ep_obj,
            steps=steps,
            tree=root_tree,
            metrics=metrics,
        )

    def find_execution_paths(
        self,
        source_id: str,
        target_id: str,
        max_depth: int = 15,
    ) -> List[List[TraceStep]]:
        """Find all simple execution paths from source_id to target_id within max_depth.

        Returns deterministic list of paths, or empty list if target is unreachable.
        """
        all_paths: List[List[TraceStep]] = []
        visited: Set[str] = {source_id}
        seen_path_keys: Set[Tuple[Tuple[str, str], ...]] = set()

        def _dfs(current_id: str, path: List[TraceStep], depth: int) -> None:
            if current_id == target_id and path:
                path_key = tuple((s.source_id, s.target_id) for s in path)
                if path_key not in seen_path_keys:
                    seen_path_keys.add(path_key)
                    all_paths.append(list(path))
                return

            if depth >= max_depth:
                return

            outgoing = sorted(
                self._adjacency.get(current_id, []),
                key=lambda s: (s.line_number or 0, s.target_id, s.call_type),
            )

            for step in outgoing:
                next_id = step.target_id
                if next_id not in visited or next_id == target_id:
                    visited.add(next_id)
                    path.append(step)
                    _dfs(next_id, path, depth + 1)
                    path.pop()
                    visited.remove(next_id)

        # Handle direct self-loop if source_id == target_id
        if source_id == target_id:
            outgoing = sorted(
                self._adjacency.get(source_id, []),
                key=lambda s: (s.line_number or 0, s.target_id, s.call_type),
            )
            for step in outgoing:
                if step.target_id == target_id:
                    all_paths.append([step])
            return all_paths

        _dfs(source_id, [], 0)

        # Sort paths deterministically by length, then by sequence of target IDs
        all_paths.sort(key=lambda p: (len(p), [s.target_id for s in p]))
        return all_paths

    def _index_parsed_files(self, parsed_files: List[ParsedFileResult]) -> None:
        """Map files and symbols for cross-referencing calls."""
        for pf in parsed_files:
            file_path = pf.file_path
            self._imports_by_file[file_path] = pf.imports

            # Dotted module indexing
            if file_path.endswith(".py"):
                stem = file_path[:-3]
                dotted = stem.replace("/", ".")
                self._module_to_file[dotted] = file_path
                parts = stem.split("/")
                for i in range(len(parts)):
                    sub_dotted = ".".join(parts[i:])
                    if sub_dotted not in self._module_to_file:
                        self._module_to_file[sub_dotted] = file_path

            def _index_sym(sym: CodeSymbol, scope: str = "") -> None:
                scoped_name = f"{scope}.{sym.name}" if scope else sym.name
                sym_id = f"symbol:{file_path}:{scoped_name}"
                self._symbol_index[file_path][sym.name] = sym_id
                if scope:
                    self._symbol_index[file_path][scoped_name] = sym_id
                for child in sym.children:
                    _index_sym(child, scoped_name)

            for sym in pf.symbols:
                _index_sym(sym)

    def _extract_calls_from_source(
        self,
        source_codes: Dict[str, str],
        parsed_files: List[ParsedFileResult],
    ) -> None:
        """Parse AST calls inside functions, methods, and CLI main blocks."""
        for file_path, code in source_codes.items():
            if not code.strip():
                continue
            try:
                tree = ast.parse(code, filename=file_path)
            except Exception:
                continue

            # A. Process if __name__ == '__main__': calls
            for node in tree.body:
                if isinstance(node, ast.If) and self._is_name_main(node):
                    caller_id = f"entrypoint:{file_path}:__main__"
                    for child in ast.walk(node):
                        if isinstance(child, ast.Call):
                            callee = self._resolve_callee_name(child.func)
                            if callee:
                                target_id = self._resolve_callee_target(callee, file_path)
                                if target_id:
                                    self.add_call_edge(
                                        source_id=caller_id,
                                        target_id=target_id,
                                        call_type="cli_invocation",
                                        line_number=child.lineno,
                                        file_path=file_path,
                                    )

            # B. Process function and method calls with recursive scope tracking
            def _scan_functions(stmts: List[ast.AST], parent_class: Optional[str] = None, scope_prefix: str = "") -> None:
                for item in stmts:
                    if isinstance(item, ast.ClassDef):
                        new_parent = f"{scope_prefix}.{item.name}" if scope_prefix else item.name
                        _scan_functions(item.body, parent_class=new_parent, scope_prefix=new_parent)
                    elif isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        func_scope = f"{scope_prefix}.{item.name}" if scope_prefix else item.name
                        caller_id = f"symbol:{file_path}:{func_scope}"
                        self._extract_function_calls(item, caller_id, file_path, parent_class)
                        _scan_functions(item.body, parent_class=parent_class, scope_prefix=func_scope)

            _scan_functions(tree.body)

    def _extract_function_calls(
        self,
        func_node: Union[ast.FunctionDef, ast.AsyncFunctionDef],
        caller_id: str,
        file_path: str,
        class_name: Optional[str],
    ) -> None:
        """Find ast.Call nodes inside function body, skipping nested function/class definitions."""
        for child in ast.iter_child_nodes(func_node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue

            def _find_calls(n: ast.AST) -> None:
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    return
                if isinstance(n, ast.Call):
                    callee = self._resolve_callee_name(n.func)
                    if callee:
                        target_id = self._resolve_callee_target(callee, file_path, class_name)
                        if target_id:
                            self.add_call_edge(
                                source_id=caller_id,
                                target_id=target_id,
                                call_type="direct_call",
                                line_number=n.lineno,
                                file_path=file_path,
                            )
                for c in ast.iter_child_nodes(n):
                    _find_calls(c)

            _find_calls(child)

    def _resolve_callee_name(self, func_node: ast.AST) -> Optional[str]:
        """Convert AST func node into identifier or dotted name."""
        if isinstance(func_node, ast.Name):
            return func_node.id
        elif isinstance(func_node, ast.Attribute):
            val = self._resolve_callee_name(func_node.value)
            return f"{val}.{func_node.attr}" if val else func_node.attr
        return None

    def _resolve_callee_target(
        self,
        callee: str,
        file_path: str,
        current_class: Optional[str] = None,
    ) -> Optional[str]:
        """Resolve a callee name (e.g. 'helper', 'self.run', 'service.do') to a symbol node ID."""
        # 1. Method invocation on self or cls
        if callee.startswith("self.") or callee.startswith("cls."):
            method_name = callee.split(".", 1)[1]
            if current_class:
                scoped = f"{current_class}.{method_name}"
                if scoped in self._symbol_index[file_path]:
                    return self._symbol_index[file_path][scoped]
            if method_name in self._symbol_index[file_path]:
                return self._symbol_index[file_path][method_name]

        # 2. Local symbol in current file
        if callee in self._symbol_index[file_path]:
            return self._symbol_index[file_path][callee]

        # 3. Check file imports
        imports = self._imports_by_file.get(file_path, [])
        for imp in imports:
            for item in imp.names:
                match_name = item.alias if item.alias else item.name

                # A. Relative imports: from .module import callee or from ..module import callee
                if imp.is_from and imp.level > 0:
                    current_dir = Path(file_path).parent
                    target_dir = current_dir
                    for _ in range(imp.level - 1):
                        target_dir = target_dir.parent

                    rel_mod = imp.module or ""
                    if rel_mod:
                        cand_posix = (target_dir / rel_mod.replace(".", "/")).as_posix()
                    else:
                        cand_posix = target_dir.as_posix()

                    if cand_posix.startswith("./"):
                        cand_posix = cand_posix[2:]

                    cand_file = f"{cand_posix}.py" if not cand_posix.endswith(".py") else cand_posix

                    if match_name == callee:
                        return f"symbol:{cand_file}:{item.name}"
                    if "." in callee:
                        prefix, func_name = callee.split(".", 1)
                        if match_name == prefix:
                            return f"symbol:{cand_file}:{item.name}.{func_name}"

                # B. Absolute from-import: from module import callee
                elif imp.is_from and match_name == callee:
                    target_module = imp.module or ""
                    target_file = self._module_to_file.get(target_module)
                    if target_file:
                        return f"symbol:{target_file}:{item.name}"
                    return f"symbol:{target_module}:{item.name}"

                # C. Absolute import: import module / service.callee (with optional alias)
                elif not imp.is_from and "." in callee:
                    prefix, func_name = callee.split(".", 1)
                    if match_name == prefix:
                        target_module = item.name
                        target_file = self._module_to_file.get(target_module)
                        if target_file:
                            return f"symbol:{target_file}:{func_name}"
                        return f"symbol:{target_module}:{func_name}"

                # D. from module import Class / Class.method call
                elif imp.is_from and "." in callee:
                    prefix, func_name = callee.split(".", 1)
                    if match_name == prefix:
                        target_module = imp.module or ""
                        target_file = self._module_to_file.get(target_module)
                        if target_file:
                            return f"symbol:{target_file}:{item.name}.{func_name}"

        return None

    def _is_name_main(self, node: ast.If) -> bool:
        """Check if ast.If test is __name__ == '__main__'."""
        test = node.test
        if isinstance(test, ast.Compare):
            left, ops, comparators = test.left, test.ops, test.comparators
            if any(isinstance(op, ast.Eq) for op in ops) and comparators:
                right = comparators[0]
                if (
                    isinstance(left, ast.Name)
                    and left.id == "__name__"
                    and isinstance(right, ast.Constant)
                    and right.value == "__main__"
                ):
                    return True
                if (
                    isinstance(left, ast.Constant)
                    and left.value == "__main__"
                    and isinstance(right, ast.Name)
                    and right.id == "__name__"
                ):
                    return True
        return False

    def _load_from_graph(self, graph: DependencyGraph) -> None:
        """Incorporate call and reference relationships from DependencyGraph."""
        for edge in graph.edges:
            if edge.edge_type == EdgeType.CALLS_OR_REFERENCES:
                file_p = self._extract_file_from_id(edge.source_id)
                self.add_call_edge(
                    source_id=edge.source_id,
                    target_id=edge.target_id,
                    call_type=edge.edge_type.value,
                    file_path=file_p,
                    metadata=edge.metadata,
                )

    def _connect_entry_points(self, entry_points: List[EntryPoint]) -> None:
        """Connect EntryPoint roots to their target handler symbols."""
        for ep in entry_points:
            if ep.symbol_id:
                self.add_call_edge(
                    source_id=ep.id,
                    target_id=ep.symbol_id,
                    call_type="route_handler" if ep.entry_type == EntryPointType.HTTP_ROUTE else "cli_invocation",
                    line_number=ep.line_number,
                    file_path=ep.file_path,
                    metadata={"entry_type": ep.entry_type.value},
                )

    def _calculate_metrics(
        self,
        entry_point: EntryPoint,
        steps: List[TraceStep],
        tree: TraceTree,
        has_cycles: bool,
    ) -> TraceMetrics:
        """Compute structural metrics for an execution trace."""
        total_steps = len(steps)

        # Max depth in tree
        def _get_max_depth(t: TraceTree) -> int:
            if not t.children:
                return t.depth
            return max(_get_max_depth(c) for c in t.children)

        max_depth = _get_max_depth(tree)

        # Branching factor: average children per non-leaf node
        non_leaf_count = 0
        total_children = 0

        def _count_branching(t: TraceTree) -> None:
            nonlocal non_leaf_count, total_children
            if t.children:
                non_leaf_count += 1
                total_children += len(t.children)
                for child in t.children:
                    _count_branching(child)

        _count_branching(tree)
        branching_factor = round(total_children / non_leaf_count, 2) if non_leaf_count > 0 else 0.0

        # Distinct files count
        files: Set[str] = set()
        if entry_point.file_path:
            files.add(entry_point.file_path)
        for s in steps:
            if s.file_path:
                files.add(s.file_path)
            src_file = self._extract_file_from_id(s.source_id)
            if src_file:
                files.add(src_file)
            tgt_file = self._extract_file_from_id(s.target_id)
            if tgt_file:
                files.add(tgt_file)

        return TraceMetrics(
            total_steps=total_steps,
            max_depth=max_depth,
            branching_factor=branching_factor,
            distinct_files_count=len(files),
            has_cycles=has_cycles,
        )

    def _extract_file_from_id(self, node_id: str) -> Optional[str]:
        """Extract file path from node ID (e.g. 'symbol:app/main.py:func' -> 'app/main.py')."""
        if node_id.startswith("symbol:"):
            parts = node_id.split(":", 2)
            if len(parts) >= 2:
                return parts[1]
        elif node_id.startswith("file:"):
            return node_id.replace("file:", "", 1)
        elif node_id.startswith("entrypoint:"):
            parts = node_id.split(":")
            if len(parts) >= 2:
                return parts[1]
        return None
