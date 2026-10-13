from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from engines.graph.analyzer import GraphAnalyzer
from engines.graph.models import (
    DependencyGraph,
    EdgeType,
    GraphEdge,
    GraphNode,
    NodeType,
)
from engines.parsing.models import CodeSymbol, ParsedFileResult, SymbolKind


class GraphBuilder:
    """Constructs a directed semantic dependency graph from ingested and parsed codebase files."""

    def __init__(self, project_id: str = "") -> None:
        self.project_id = project_id

    def build(
        self,
        parsed_files: List[ParsedFileResult],
        all_relative_paths: Optional[List[str]] = None,
    ) -> DependencyGraph:
        """Construct graph nodes, containment edges, import dependencies, and inheritance relationships."""
        nodes_by_id: Dict[str, GraphNode] = {}
        edges_by_key: Dict[Tuple[str, str, EdgeType], GraphEdge] = {}

        # 1. Index project file paths
        known_files: Set[str] = {f.file_path for f in parsed_files}
        if all_relative_paths:
            known_files.update(all_relative_paths)

        # Index internal module names to file paths
        module_to_file = self._build_module_index(known_files)

        # Index symbols by file path: file_path -> {symbol_name: symbol_node_id}
        symbol_index: Dict[str, Dict[str, str]] = defaultdict(dict)

        # Track classes for second-pass inheritance resolution: list of (file_path, sym_id, CodeSymbol)
        classes_to_resolve: List[Tuple[str, str, CodeSymbol]] = []

        # 2. Create File Nodes and Symbol Hierarchy with Containment Edges
        for parsed in parsed_files:
            file_id = f"file:{parsed.file_path}"
            if file_id not in nodes_by_id:
                nodes_by_id[file_id] = GraphNode(
                    id=file_id,
                    name=Path(parsed.file_path).name,
                    node_type=NodeType.FILE,
                    file_path=parsed.file_path,
                    metadata={"language": parsed.language, "total_lines": parsed.total_lines},
                )

            # Process top-level symbols
            for sym in parsed.symbols:
                self._add_symbol_hierarchy(
                    parsed.file_path,
                    file_id,
                    sym,
                    nodes_by_id,
                    edges_by_key,
                    symbol_index,
                    classes_to_resolve,
                )

        # 3. Resolve Class Inheritance Edges (after all symbol nodes exist)
        imports_by_file: Dict[str, List] = {p.file_path: p.imports for p in parsed_files}
        for file_path, sym_id, sym in classes_to_resolve:
            base_classes = getattr(sym, "base_classes", [])
            file_imports = imports_by_file.get(file_path, [])

            for base in base_classes:
                base_target_id = self._resolve_base_class(
                    file_path=file_path,
                    base_name=base,
                    symbol_index=symbol_index,
                    file_imports=file_imports,
                    known_files=known_files,
                    module_to_file=module_to_file,
                    nodes_by_id=nodes_by_id,
                )

                if base_target_id:
                    inherit_key = (sym_id, base_target_id, EdgeType.INHERITS_FROM)
                    if inherit_key not in edges_by_key:
                        edges_by_key[inherit_key] = GraphEdge(
                            source_id=sym_id,
                            target_id=base_target_id,
                            edge_type=EdgeType.INHERITS_FROM,
                            weight=1.0,
                            metadata={"base_class": base},
                        )

        # 4. Resolve Import Statements and Create Dependency Edges
        for parsed in parsed_files:
            source_file_id = f"file:{parsed.file_path}"

            for imp in parsed.imports:
                targets_to_process: List[Tuple[Optional[str], bool, List[str]]] = []

                if not imp.is_from:
                    # 'import x, y as z' -> each name is an independent module/package
                    for item in imp.names:
                        target_id, is_internal = self._resolve_single_import(
                            current_file_path=parsed.file_path,
                            module=item.name,
                            level=0,
                            imported_names=[],
                            known_files=known_files,
                            module_to_file=module_to_file,
                            nodes_by_id=nodes_by_id,
                        )
                        if target_id:
                            targets_to_process.append((target_id, is_internal, [item.name]))
                else:
                    # 'from x import a, b' or 'from . import a'
                    names_list = [item.name for item in imp.names]
                    target_id, is_internal = self._resolve_single_import(
                        current_file_path=parsed.file_path,
                        module=imp.module,
                        level=imp.level,
                        imported_names=names_list,
                        known_files=known_files,
                        module_to_file=module_to_file,
                        nodes_by_id=nodes_by_id,
                    )
                    if target_id:
                        targets_to_process.append((target_id, is_internal, names_list))

                for target_node_id, is_internal, symbols_list in targets_to_process:
                    edge_key = (source_file_id, target_node_id, EdgeType.IMPORTS)

                    if edge_key in edges_by_key:
                        existing = edges_by_key[edge_key]
                        existing.weight += 1.0
                        existing_symbols = existing.metadata.get("symbols", [])
                        for s in symbols_list:
                            if s not in existing_symbols:
                                existing_symbols.append(s)
                    else:
                        edges_by_key[edge_key] = GraphEdge(
                            source_id=source_file_id,
                            target_id=target_node_id,
                            edge_type=EdgeType.IMPORTS,
                            weight=1.0,
                            metadata={
                                "symbols": symbols_list,
                                "is_from": imp.is_from,
                                "level": imp.level,
                                "line_number": imp.line_number,
                            },
                        )

                    # If internal, add call/reference edge to target symbol if matched
                    if is_internal and target_node_id.startswith("file:"):
                        target_file_path = target_node_id.replace("file:", "", 1)
                        target_symbols = symbol_index.get(target_file_path, {})
                        for s_name in symbols_list:
                            if s_name in target_symbols:
                                ref_target_id = target_symbols[s_name]
                                ref_edge_key = (source_file_id, ref_target_id, EdgeType.CALLS_OR_REFERENCES)
                                if ref_edge_key not in edges_by_key:
                                    edges_by_key[ref_edge_key] = GraphEdge(
                                        source_id=source_file_id,
                                        target_id=ref_target_id,
                                        edge_type=EdgeType.CALLS_OR_REFERENCES,
                                        weight=1.0,
                                        metadata={"symbol_name": s_name, "line_number": imp.line_number},
                                    )

        nodes = list(nodes_by_id.values())
        edges = list(edges_by_key.values())

        # 5. Compute metrics and cycles
        metrics = GraphAnalyzer.calculate_metrics(nodes, edges)
        cycles = GraphAnalyzer.detect_cycles(edges)

        return DependencyGraph(
            project_id=self.project_id,
            nodes=nodes,
            edges=edges,
            metrics=metrics,
            cycles=cycles,
        )

    def _add_symbol_hierarchy(
        self,
        file_path: str,
        parent_id: str,
        sym: CodeSymbol,
        nodes_by_id: Dict[str, GraphNode],
        edges_by_key: Dict[Tuple[str, str, EdgeType], GraphEdge],
        symbol_index: Dict[str, Dict[str, str]],
        classes_to_resolve: List[Tuple[str, str, CodeSymbol]],
        scope_prefix: str = "",
    ) -> None:
        """Recursively add symbol nodes and CONTAINS edges."""
        scoped_name = f"{scope_prefix}.{sym.name}" if scope_prefix else sym.name
        sym_id = f"symbol:{file_path}:{scoped_name}"

        node_kind = NodeType.FUNCTION
        if sym.kind == SymbolKind.CLASS:
            node_kind = NodeType.CLASS
        elif sym.kind == SymbolKind.METHOD:
            node_kind = NodeType.METHOD
        elif sym.kind == SymbolKind.ASYNC_FUNCTION:
            node_kind = NodeType.ASYNC_FUNCTION

        if sym_id not in nodes_by_id:
            nodes_by_id[sym_id] = GraphNode(
                id=sym_id,
                name=sym.name,
                node_type=node_kind,
                file_path=file_path,
                line_number=sym.start_line,
                metadata={
                    "complexity": sym.complexity,
                    "return_type": sym.return_type,
                    "docstring": sym.docstring,
                    "decorators": sym.decorators,
                },
            )

        symbol_index[file_path][sym.name] = sym_id

        # Structural containment edge
        contain_key = (parent_id, sym_id, EdgeType.CONTAINS)
        if contain_key not in edges_by_key:
            edges_by_key[contain_key] = GraphEdge(
                source_id=parent_id,
                target_id=sym_id,
                edge_type=EdgeType.CONTAINS,
                weight=1.0,
            )

        if sym.kind == SymbolKind.CLASS:
            classes_to_resolve.append((file_path, sym_id, sym))

        # Recurse for nested symbols
        for child in sym.children:
            self._add_symbol_hierarchy(
                file_path,
                sym_id,
                child,
                nodes_by_id,
                edges_by_key,
                symbol_index,
                classes_to_resolve,
                scope_prefix=scoped_name,
            )

    def _resolve_base_class(
        self,
        file_path: str,
        base_name: str,
        symbol_index: Dict[str, Dict[str, str]],
        file_imports: List,
        known_files: Set[str],
        module_to_file: Dict[str, str],
        nodes_by_id: Dict[str, GraphNode],
    ) -> str:
        """Resolve a base class identifier to a defined symbol node or external node."""
        # 1. Base class defined in same file
        if base_name in symbol_index[file_path]:
            return symbol_index[file_path][base_name]

        # 2. Base class imported from another file or module
        for imp in file_imports:
            for item in imp.names:
                match_name = item.alias if item.alias else item.name
                if match_name == base_name:
                    module_arg = imp.module if imp.is_from else item.name
                    level_arg = imp.level if imp.is_from else 0
                    target_id, is_internal = self._resolve_single_import(
                        file_path,
                        module_arg,
                        level_arg,
                        [item.name],
                        known_files,
                        module_to_file,
                        nodes_by_id,
                    )
                    if is_internal and target_id and target_id.startswith("file:"):
                        target_file = target_id.replace("file:", "", 1)
                        if item.name in symbol_index.get(target_file, {}):
                            return symbol_index[target_file][item.name]
                        # Target symbol in target file
                        sym_target = f"symbol:{target_file}:{item.name}"
                        if sym_target not in nodes_by_id:
                            nodes_by_id[sym_target] = GraphNode(
                                id=sym_target,
                                name=item.name,
                                node_type=NodeType.CLASS,
                                file_path=target_file,
                                metadata={"inferred": True},
                            )
                        return sym_target
                    elif target_id:
                        return target_id

        # 3. Fallback: create or reuse symbol node in current file
        base_id = f"symbol:{file_path}:{base_name}"
        if base_id not in nodes_by_id:
            nodes_by_id[base_id] = GraphNode(
                id=base_id,
                name=base_name,
                node_type=NodeType.CLASS,
                file_path=file_path,
                metadata={"inferred": True},
            )
        return base_id

    def _build_module_index(self, known_files: Set[str]) -> Dict[str, str]:
        """Map dotted Python module strings to project relative file paths."""
        index: Dict[str, str] = {}
        for path_str in sorted(known_files):
            if not path_str.endswith(".py"):
                continue

            clean_stem = path_str[:-3]
            dotted = clean_stem.replace("/", ".")

            index[dotted] = path_str

            # Handle __init__.py package module name
            if clean_stem.endswith("/__init__"):
                pkg_dotted = clean_stem[:-9].replace("/", ".")
                index[pkg_dotted] = path_str
            elif clean_stem == "__init__":
                index[""] = path_str

            # Handle suffix modules for subdirectories (e.g. 'app.services.projects')
            parts = clean_stem.split("/")
            for i in range(len(parts)):
                sub_dotted = ".".join(parts[i:])
                if sub_dotted not in index:
                    index[sub_dotted] = path_str

        return index

    def _resolve_single_import(
        self,
        current_file_path: str,
        module: Optional[str],
        level: int,
        imported_names: List[str],
        known_files: Set[str],
        module_to_file: Dict[str, str],
        nodes_by_id: Dict[str, GraphNode],
    ) -> Tuple[Optional[str], bool]:
        """Resolve an import specification to either an internal file node or an external package node."""
        # A. Relative Import Resolution (level > 0)
        if level > 0:
            current_dir = Path(current_file_path).parent

            # Ascend according to level: level 1 is current dir, level 2 is parent, etc.
            target_dir = current_dir
            for _ in range(level - 1):
                target_dir = target_dir.parent

            # Sub-module path if specified
            if module:
                cand_posix = (target_dir / module.replace(".", "/")).as_posix()
                if cand_posix.startswith("./"):
                    cand_posix = cand_posix[2:]
                if f"{cand_posix}.py" in known_files:
                    return f"file:{cand_posix}.py", True
                if f"{cand_posix}/__init__.py" in known_files:
                    return f"file:{cand_posix}/__init__.py", True

            # If no module or relative import names match a module file in target dir
            for name in imported_names:
                cand_posix = (target_dir / name).as_posix()
                if cand_posix.startswith("./"):
                    cand_posix = cand_posix[2:]
                if f"{cand_posix}.py" in known_files:
                    return f"file:{cand_posix}.py", True
                if f"{cand_posix}/__init__.py" in known_files:
                    return f"file:{cand_posix}/__init__.py", True

            # Fallback relative directory __init__.py match
            target_posix = target_dir.as_posix()
            init_cand = "__init__.py" if target_posix == "." else f"{target_posix}/__init__.py"
            if init_cand in known_files:
                return f"file:{init_cand}", True

            # Fallback relative file node even if not parsed
            rel_name = module or (imported_names[0] if imported_names else "relative")
            target_str = (target_dir / rel_name.replace(".", "/")).as_posix()
            if target_str.startswith("./"):
                target_str = target_str[2:]
            unresolved_id = f"file:{target_str}"
            if unresolved_id not in nodes_by_id:
                nodes_by_id[unresolved_id] = GraphNode(
                    id=unresolved_id,
                    name=Path(target_str).name,
                    node_type=NodeType.FILE,
                    file_path=target_str,
                    metadata={"unresolved": True},
                )
            return unresolved_id, True

        # B. Absolute Internal Import Resolution
        if module:
            # 1. Exact match in module index
            if module in module_to_file:
                return f"file:{module_to_file[module]}", True

            # 2. Check path suffix match
            mod_posix = module.replace(".", "/")
            for kf in sorted(known_files):
                if kf == f"{mod_posix}.py" or kf == f"{mod_posix}/__init__.py":
                    return f"file:{kf}", True
                if kf.endswith(f"/{mod_posix}.py") or kf.endswith(f"/{mod_posix}/__init__.py"):
                    return f"file:{kf}", True

            # 3. Check if module + imported name matches a file
            for name in imported_names:
                combined_posix = f"{mod_posix}/{name}"
                for kf in sorted(known_files):
                    if kf == f"{combined_posix}.py" or kf.endswith(f"/{combined_posix}.py"):
                        return f"file:{kf}", True

        # C. External Package Resolution
        root_pkg = "unknown"
        if module:
            root_pkg = module.split(".")[0]
        elif imported_names:
            root_pkg = imported_names[0].split(".")[0]

        ext_id = f"external:{root_pkg}"
        if ext_id not in nodes_by_id:
            nodes_by_id[ext_id] = GraphNode(
                id=ext_id,
                name=root_pkg,
                node_type=NodeType.EXTERNAL_PACKAGE,
            )

        return ext_id, False

    def _resolve_import_target(
        self,
        current_file_path: str,
        module: Optional[str],
        level: int,
        imported_names: List[str],
        known_files: Set[str],
        module_to_file: Dict[str, str],
        nodes_by_id: Dict[str, GraphNode],
    ) -> Tuple[Optional[str], bool]:
        """Backward-compatible alias for _resolve_single_import."""
        return self._resolve_single_import(
            current_file_path=current_file_path,
            module=module,
            level=level,
            imported_names=imported_names,
            known_files=known_files,
            module_to_file=module_to_file,
            nodes_by_id=nodes_by_id,
        )
