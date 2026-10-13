import pytest

from engines.analysis import (
    EntryPoint,
    EntryPointDetector,
    EntryPointType,
    ExecutionTrace,
    ExecutionTracer,
    TraceMetrics,
    TraceStep,
    TraceTree,
    parse_route_decorator,
)
from engines.graph import DependencyGraph, EdgeType, GraphEdge, GraphNode, NodeType
from engines.parsing import PythonAstParser


def test_fastapi_route_decorator_detection():
    """Verify detection of various FastAPI HTTP route decorators."""
    code = '''
from fastapi import APIRouter

router = APIRouter()

@router.get("/users")
def get_users():
    return []

@router.post("/users/{user_id}/activate")
async def activate_user(user_id: int):
    return {"status": "ok"}

@router.delete("/items/{item_id}")
def delete_item(item_id: str):
    pass
'''
    parser = PythonAstParser()
    parsed = parser.parse_source(code, file_path="app/api/users.py")

    detector = EntryPointDetector()
    entry_points = detector.detect_from_parsed_file(parsed, code=code)

    assert len(entry_points) == 3
    ep_map = {ep.name: ep for ep in entry_points}

    assert "get_users" in ep_map
    assert ep_map["get_users"].http_method == "GET"
    assert ep_map["get_users"].route_path == "/users"
    assert ep_map["get_users"].entry_type == EntryPointType.HTTP_ROUTE
    assert ep_map["get_users"].symbol_id == "symbol:app/api/users.py:get_users"

    assert "activate_user" in ep_map
    assert ep_map["activate_user"].http_method == "POST"
    assert ep_map["activate_user"].route_path == "/users/{user_id}/activate"

    assert "delete_item" in ep_map
    assert ep_map["delete_item"].http_method == "DELETE"
    assert ep_map["delete_item"].route_path == "/items/{item_id}"


def test_flask_route_decorator_detection():
    """Verify detection of Flask @app.route decorators with multiple HTTP methods."""
    code = '''
from flask import Flask

app = Flask(__name__)

@app.route("/login", methods=["POST", "GET"])
def login():
    return "ok"

@app.route("/health")
def health():
    return "healthy"
'''
    detector = EntryPointDetector()
    entry_points = detector.detect_from_code(code, file_path="app/views.py")

    assert len(entry_points) == 2
    ep_map = {ep.name: ep for ep in entry_points}

    assert "login" in ep_map
    assert ep_map["login"].http_method == "POST"
    assert ep_map["login"].route_path == "/login"
    assert "GET" in ep_map["login"].metadata.get("methods", [])

    assert "health" in ep_map
    assert ep_map["health"].http_method == "GET"
    assert ep_map["health"].route_path == "/health"


def test_main_block_cli_detection():
    """Verify detection of if __name__ == '__main__': blocks as CLI entrypoints."""
    code = '''
def main():
    print("running")

if __name__ == "__main__":
    main()
'''
    detector = EntryPointDetector()
    entry_points = detector.detect_from_code(code, file_path="scripts/run.py")

    assert len(entry_points) == 1
    cli_ep = entry_points[0]
    assert cli_ep.name == "__main__"
    assert cli_ep.entry_type == EntryPointType.CLI_SCRIPT
    assert cli_ep.file_path == "scripts/run.py"
    assert cli_ep.symbol_id == "symbol:scripts/run.py:__main__"


def test_deterministic_call_path_traversal():
    """Verify deterministic DFS execution trace order and step sequencing."""
    tracer = ExecutionTracer()

    # Build call hierarchy: root -> B -> D
    #                       root -> A -> C
    # Regardless of insertion order, A comes before B deterministically (alphabetical / line number)
    tracer.add_call_edge("root", "B", line_number=20)
    tracer.add_call_edge("root", "A", line_number=10)
    tracer.add_call_edge("A", "C", line_number=15)
    tracer.add_call_edge("B", "D", line_number=25)

    trace = tracer.trace_execution("root", max_depth=10)

    assert trace.entry_point.id == "root"
    assert len(trace.steps) == 4

    # Verification of deterministic sequence: A (line 10), then C (line 15), then B (line 20), then D (line 25)
    target_sequence = [s.target_id for s in trace.steps]
    assert target_sequence == ["A", "C", "B", "D"]

    # Verify step indices are sequential
    for i, step in enumerate(trace.steps):
        assert step.step_index == i

    # Verify tree structure
    assert trace.tree is not None
    assert trace.tree.node_id == "root"
    assert len(trace.tree.children) == 2
    assert trace.tree.children[0].node_id == "A"
    assert trace.tree.children[0].children[0].node_id == "C"
    assert trace.tree.children[1].node_id == "B"
    assert trace.tree.children[1].children[0].node_id == "D"


def test_branching_and_metrics_calculation():
    """Verify branching factor, max depth, step counts, and distinct files metrics."""
    tracer = ExecutionTracer()

    # root (file: a.py) calls:
    #   - handler1 (file: b.py) -> helper1 (file: c.py)
    #   - handler2 (file: b.py) -> helper2 (file: c.py)
    # Non-leaf nodes: root (2 children), handler1 (1 child), handler2 (1 child).
    # Total non-leaf = 3, total children = 4. Average branching = 4 / 3 = 1.33.
    tracer.add_call_edge("symbol:a.py:root", "symbol:b.py:handler1", line_number=10, file_path="a.py")
    tracer.add_call_edge("symbol:a.py:root", "symbol:b.py:handler2", line_number=20, file_path="a.py")
    tracer.add_call_edge("symbol:b.py:handler1", "symbol:c.py:helper1", line_number=30, file_path="b.py")
    tracer.add_call_edge("symbol:b.py:handler2", "symbol:c.py:helper2", line_number=40, file_path="b.py")

    trace = tracer.trace_execution("symbol:a.py:root", max_depth=10)

    assert trace.metrics.total_steps == 4
    assert trace.metrics.max_depth == 2
    assert trace.metrics.branching_factor == 1.33
    assert trace.metrics.distinct_files_count == 3
    assert not trace.metrics.has_cycles


def test_source_to_target_pathfinding():
    """Verify finding all simple paths between source and target nodes."""
    tracer = ExecutionTracer()

    # Diamond call graph:
    # S -> A -> T
    # S -> B -> T
    # S -> C (does not lead to T)
    tracer.add_call_edge("S", "A", line_number=1)
    tracer.add_call_edge("A", "T", line_number=2)
    tracer.add_call_edge("S", "B", line_number=3)
    tracer.add_call_edge("B", "T", line_number=4)
    tracer.add_call_edge("S", "C", line_number=5)

    paths = tracer.find_execution_paths("S", "T", max_depth=5)

    assert len(paths) == 2
    path_targets = [[s.target_id for s in p] for p in paths]
    assert ["A", "T"] in path_targets
    assert ["B", "T"] in path_targets


def test_unreachable_target_returns_empty_list():
    """Verify that pathfinding to an unreachable target returns an empty list."""
    tracer = ExecutionTracer()

    tracer.add_call_edge("A", "B", line_number=1)
    tracer.add_call_edge("B", "C", line_number=2)
    tracer.add_call_edge("X", "Y", line_number=3)

    paths = tracer.find_execution_paths("A", "Y", max_depth=10)
    assert paths == []


def test_cycle_and_recursion_protection():
    """Verify that cycles and recursive calls do not cause infinite loops and are flagged."""
    tracer = ExecutionTracer()

    # Cycle: A -> B -> C -> A
    tracer.add_call_edge("A", "B", line_number=1)
    tracer.add_call_edge("B", "C", line_number=2)
    tracer.add_call_edge("C", "A", line_number=3)

    trace = tracer.trace_execution("A", max_depth=10)

    assert trace.metrics.has_cycles is True
    # Steps: A -> B, B -> C, C -> A (cycle step)
    assert len(trace.steps) == 3
    assert trace.steps[-1].metadata.get("is_cycle") is True

    # Pathfinding in cyclic graph does not loop infinitely
    paths = tracer.find_execution_paths("A", "C", max_depth=10)
    assert len(paths) == 1
    assert [s.target_id for s in paths[0]] == ["B", "C"]


def test_max_depth_enforcement():
    """Verify that traversal halts when max_depth is reached."""
    tracer = ExecutionTracer()

    # Linear chain of 5 steps: N0 -> N1 -> N2 -> N3 -> N4 -> N5
    for i in range(5):
        tracer.add_call_edge(f"N{i}", f"N{i+1}", line_number=i + 1)

    # Limit depth to 2
    trace = tracer.trace_execution("N0", max_depth=2)

    assert trace.metrics.max_depth == 2
    # At depth 2, traversal halts at N2; exactly 2 steps taken (N0->N1, N1->N2)
    assert len(trace.steps) == 2
    assert trace.steps[-1].target_id == "N2"
    # N2 tree node has depth_limited set
    assert trace.tree.children[0].children[0].metadata.get("depth_limited") is True


def test_end_to_end_ast_code_tracing():
    """Verify end-to-end extraction from Python AST and tracing of entrypoints and calls."""
    code_api = '''
from app.services import process_order

@router.post("/orders")
def create_order():
    return process_order()
'''

    code_services = '''
def process_order():
    validate()
    save()

def validate():
    pass

def save():
    pass
'''

    source_codes = {
        "app/api.py": code_api,
        "app/services.py": code_services,
    }

    parser = PythonAstParser()
    parsed_api = parser.parse_source(code_api, file_path="app/api.py")
    parsed_services = parser.parse_source(code_services, file_path="app/services.py")

    detector = EntryPointDetector()
    entry_points = detector.detect_all([parsed_api, parsed_services], source_codes=source_codes)

    assert len(entry_points) == 1
    ep = entry_points[0]
    assert ep.http_method == "POST"
    assert ep.route_path == "/orders"

    tracer = ExecutionTracer(
        parsed_files=[parsed_api, parsed_services],
        source_codes=source_codes,
        entry_points=entry_points,
    )

    trace = tracer.trace_execution(ep, max_depth=10)

    # Flow:
    # 1. entrypoint:app/api.py:POST:/orders -> symbol:app/api.py:create_order (route_handler)
    # 2. symbol:app/api.py:create_order -> symbol:app/services.py:process_order (direct_call)
    # 3. symbol:app/services.py:process_order -> symbol:app/services.py:validate (direct_call)
    # 4. symbol:app/services.py:process_order -> symbol:app/services.py:save (direct_call)
    assert len(trace.steps) == 4
    step_targets = [s.target_id for s in trace.steps]
    assert "symbol:app/api.py:create_order" in step_targets
    assert "symbol:app/services.py:process_order" in step_targets
    assert "symbol:app/services.py:validate" in step_targets
    assert "symbol:app/services.py:save" in step_targets

    assert trace.metrics.distinct_files_count == 2
    assert trace.metrics.has_cycles is False


def test_edge_case_aliases_and_relative_imports():
    """Verify imported calls with aliases and relative import resolution."""
    code_consumer = '''
from .helpers import calculate as calc_helper
import math as m

def compute(x):
    return calc_helper(x)
'''
    code_helpers = '''
def calculate(n):
    return n * 2
'''
    source_codes = {
        "pkg/consumer.py": code_consumer,
        "pkg/helpers.py": code_helpers,
    }

    parser = PythonAstParser()
    p_consumer = parser.parse_source(code_consumer, file_path="pkg/consumer.py")
    p_helpers = parser.parse_source(code_helpers, file_path="pkg/helpers.py")

    tracer = ExecutionTracer(
        parsed_files=[p_consumer, p_helpers],
        source_codes=source_codes,
    )

    trace = tracer.trace_execution("symbol:pkg/consumer.py:compute", max_depth=5)
    assert len(trace.steps) == 1
    assert trace.steps[0].target_id == "symbol:pkg/helpers.py:calculate"


def test_edge_case_class_methods_and_nested_functions():
    """Verify class method self-calls and nested inner function calls."""
    code = '''
class Service:
    def execute(self):
        self.step_one()

    def step_one(self):
        def inner_worker():
            pass
        inner_worker()
'''
    source_codes = {"app/service.py": code}
    parser = PythonAstParser()
    parsed = parser.parse_source(code, file_path="app/service.py")

    tracer = ExecutionTracer(
        parsed_files=[parsed],
        source_codes=source_codes,
    )

    trace = tracer.trace_execution("symbol:app/service.py:Service.execute", max_depth=5)

    assert len(trace.steps) == 2
    assert trace.steps[0].target_id == "symbol:app/service.py:Service.step_one"
    assert trace.steps[1].target_id == "symbol:app/service.py:Service.step_one.inner_worker"


def test_edge_case_duplicate_paths_deduplication():
    """Verify that multiple calls to the same target do not produce duplicate paths in pathfinding."""
    tracer = ExecutionTracer()

    # Two call sites from A to B (e.g. at line 5 and line 10)
    tracer.add_call_edge("A", "B", line_number=5)
    tracer.add_call_edge("A", "B", line_number=10)
    tracer.add_call_edge("B", "C", line_number=15)

    paths = tracer.find_execution_paths("A", "C", max_depth=5)
    # Deduplicated path list should contain exactly one simple path from A to C
    assert len(paths) == 1
    assert [s.target_id for s in paths[0]] == ["B", "C"]


def test_edge_case_malformed_syntax_resilience():
    """Verify that malformed source codes and invalid syntax do not crash tracer or detector."""
    malformed_code = "def broken(::"
    detector = EntryPointDetector()
    entry_points = detector.detect_from_code(malformed_code, file_path="broken.py")
    assert entry_points == []

    tracer = ExecutionTracer(source_codes={"broken.py": malformed_code})
    trace = tracer.trace_execution("nonexistent_root", max_depth=5)
    assert trace.steps == []
    assert trace.metrics.total_steps == 0


def test_dependency_graph_calls_or_references_integration():
    """Verify integration with Feature #7 DependencyGraph CALLS_OR_REFERENCES edges."""
    node_a = GraphNode(id="symbol:app/a.py:func_a", name="func_a", node_type=NodeType.FUNCTION, file_path="app/a.py")
    node_b = GraphNode(id="symbol:app/b.py:func_b", name="func_b", node_type=NodeType.FUNCTION, file_path="app/b.py")
    edge = GraphEdge(
        source_id="symbol:app/a.py:func_a",
        target_id="symbol:app/b.py:func_b",
        edge_type=EdgeType.CALLS_OR_REFERENCES,
        metadata={"line_number": 42},
    )
    graph = DependencyGraph(
        project_id="test-proj",
        nodes=[node_a, node_b],
        edges=[edge],
    )

    tracer = ExecutionTracer(graph=graph)
    trace = tracer.trace_execution("symbol:app/a.py:func_a", max_depth=5)

    assert len(trace.steps) == 1
    assert trace.steps[0].target_id == "symbol:app/b.py:func_b"
    assert trace.steps[0].call_type == "calls_or_references"
    assert trace.metrics.total_steps == 1
    assert trace.metrics.distinct_files_count == 2

