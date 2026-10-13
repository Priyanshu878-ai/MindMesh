from pathlib import Path
import pytest

from engines.graph import (
    DependencyGraph,
    EdgeType,
    GraphAnalyzer,
    GraphBuilder,
    GraphEdge,
    GraphMetrics,
    GraphNode,
    NodeType,
)
from engines.parsing import CodeParser, PythonAstParser


def test_graph_node_and_containment_hierarchy():
    """Verify that file, class, method, and function nodes are created with CONTAINS edges."""
    code = '''
class Greeter:
    def greet(self, name: str) -> str:
        return f"Hello, {name}"

def standalone_helper() -> int:
    return 42
'''
    parser = PythonAstParser()
    parsed = parser.parse_source(code, file_path="app/greeter.py")

    builder = GraphBuilder(project_id="test-proj")
    graph = builder.build([parsed])

    node_ids = {n.id: n for n in graph.nodes}
    assert "file:app/greeter.py" in node_ids
    assert "symbol:app/greeter.py:Greeter" in node_ids
    assert "symbol:app/greeter.py:Greeter.greet" in node_ids
    assert "symbol:app/greeter.py:standalone_helper" in node_ids

    assert node_ids["file:app/greeter.py"].node_type == NodeType.FILE
    assert node_ids["symbol:app/greeter.py:Greeter"].node_type == NodeType.CLASS
    assert node_ids["symbol:app/greeter.py:Greeter.greet"].node_type == NodeType.METHOD
    assert node_ids["symbol:app/greeter.py:standalone_helper"].node_type == NodeType.FUNCTION

    # Check CONTAINS edges
    contain_edges = [
        (e.source_id, e.target_id)
        for e in graph.edges
        if e.edge_type == EdgeType.CONTAINS
    ]
    assert ("file:app/greeter.py", "symbol:app/greeter.py:Greeter") in contain_edges
    assert ("symbol:app/greeter.py:Greeter", "symbol:app/greeter.py:Greeter.greet") in contain_edges
    assert ("file:app/greeter.py", "symbol:app/greeter.py:standalone_helper") in contain_edges


def test_class_inheritance_edges():
    """Verify INHERITS_FROM relationships for intra-file and cross-file base classes."""
    base_code = '''
class Animal:
    def sound(self) -> str:
        return "..."
'''
    derived_code = '''
from animals.base import Animal

class Dog(Animal):
    def sound(self) -> str:
        return "Woof"

class Labrador(Dog):
    pass
'''
    parser = PythonAstParser()
    parsed_base = parser.parse_source(base_code, file_path="animals/base.py")
    parsed_derived = parser.parse_source(derived_code, file_path="animals/derived.py")

    builder = GraphBuilder(project_id="test-proj")
    graph = builder.build([parsed_base, parsed_derived])

    inherit_edges = [
        (e.source_id, e.target_id)
        for e in graph.edges
        if e.edge_type == EdgeType.INHERITS_FROM
    ]

    # Dog inherits from Animal (cross-file resolution)
    assert ("symbol:animals/derived.py:Dog", "symbol:animals/base.py:Animal") in inherit_edges

    # Labrador inherits from Dog (same-file resolution)
    assert ("symbol:animals/derived.py:Labrador", "symbol:animals/derived.py:Dog") in inherit_edges


def test_internal_and_external_imports():
    """Verify internal module resolution and external package node classification."""
    source_code = '''
import os
import sys
from typing import List, Optional
from math import sqrt
from app.services.users import UserService
from .helpers import format_name
'''
    parser = PythonAstParser()
    parsed = parser.parse_source(source_code, file_path="app/controllers/main.py")

    all_files = [
        "app/controllers/main.py",
        "app/controllers/helpers.py",
        "app/services/users.py",
    ]

    builder = GraphBuilder(project_id="test-proj")
    graph = builder.build([parsed], all_relative_paths=all_files)

    node_ids = {n.id: n for n in graph.nodes}

    # External nodes created
    assert "external:os" in node_ids
    assert "external:sys" in node_ids
    assert "external:typing" in node_ids
    assert "external:math" in node_ids
    assert node_ids["external:os"].node_type == NodeType.EXTERNAL_PACKAGE

    # Internal import edges
    import_edges = [
        (e.source_id, e.target_id)
        for e in graph.edges
        if e.edge_type == EdgeType.IMPORTS
    ]

    # Absolute internal import
    assert ("file:app/controllers/main.py", "file:app/services/users.py") in import_edges
    # Relative internal import
    assert ("file:app/controllers/main.py", "file:app/controllers/helpers.py") in import_edges
    # External import edges
    assert ("file:app/controllers/main.py", "external:os") in import_edges
    assert ("file:app/controllers/main.py", "external:typing") in import_edges


def test_calls_or_references_edges():
    """Verify that importing a specific symbol creates a CALLS_OR_REFERENCES edge."""
    models_code = '''
class User:
    pass
'''
    service_code = '''
from app.models import User
'''
    parser = PythonAstParser()
    p_models = parser.parse_source(models_code, file_path="app/models.py")
    p_service = parser.parse_source(service_code, file_path="app/service.py")

    builder = GraphBuilder(project_id="test-proj")
    graph = builder.build([p_models, p_service])

    ref_edges = [
        (e.source_id, e.target_id)
        for e in graph.edges
        if e.edge_type == EdgeType.CALLS_OR_REFERENCES
    ]
    assert ("file:app/service.py", "symbol:app/models.py:User") in ref_edges


def test_cycle_detection_deterministic():
    """Verify that dependency cycles are detected deterministically and canonicalized."""
    edges = [
        GraphEdge(source_id="file:a.py", target_id="file:b.py", edge_type=EdgeType.IMPORTS),
        GraphEdge(source_id="file:b.py", target_id="file:c.py", edge_type=EdgeType.IMPORTS),
        GraphEdge(source_id="file:c.py", target_id="file:a.py", edge_type=EdgeType.IMPORTS),
        GraphEdge(source_id="file:x.py", target_id="file:y.py", edge_type=EdgeType.IMPORTS),
    ]

    cycles = GraphAnalyzer.detect_cycles(edges)
    assert len(cycles) == 1
    # Canonical rotation should start with lexicographically smallest node
    assert cycles[0] == ["file:a.py", "file:b.py", "file:c.py", "file:a.py"]

    # Two mutually dependent nodes
    two_node_edges = [
        GraphEdge(source_id="file:beta.py", target_id="file:alpha.py", edge_type=EdgeType.IMPORTS),
        GraphEdge(source_id="file:alpha.py", target_id="file:beta.py", edge_type=EdgeType.IMPORTS),
    ]
    two_cycles = GraphAnalyzer.detect_cycles(two_node_edges)
    assert len(two_cycles) == 1
    assert two_cycles[0] == ["file:alpha.py", "file:beta.py", "file:alpha.py"]


def test_acyclic_graph_returns_no_cycles():
    """Verify that a DAG has zero detected cycles."""
    edges = [
        GraphEdge(source_id="file:a.py", target_id="file:b.py", edge_type=EdgeType.IMPORTS),
        GraphEdge(source_id="file:b.py", target_id="file:c.py", edge_type=EdgeType.IMPORTS),
        GraphEdge(source_id="file:a.py", target_id="file:c.py", edge_type=EdgeType.IMPORTS),
    ]
    cycles = GraphAnalyzer.detect_cycles(edges)
    assert cycles == []


def test_graph_metrics_calculation():
    """Verify degrees, node/edge type distributions, and isolation counts."""
    nodes = [
        GraphNode(id="file:1", name="1", node_type=NodeType.FILE),
        GraphNode(id="file:2", name="2", node_type=NodeType.FILE),
        GraphNode(id="class:1", name="C1", node_type=NodeType.CLASS),
        GraphNode(id="isolated:1", name="Iso", node_type=NodeType.FILE),
    ]
    edges = [
        GraphEdge(source_id="file:1", target_id="file:2", edge_type=EdgeType.IMPORTS),
        GraphEdge(source_id="file:1", target_id="class:1", edge_type=EdgeType.CONTAINS),
    ]

    metrics = GraphAnalyzer.calculate_metrics(nodes, edges)

    assert metrics.total_nodes == 4
    assert metrics.total_edges == 2
    assert metrics.isolated_nodes_count == 1
    assert metrics.out_degrees["file:1"] == 2
    assert metrics.in_degrees["file:1"] == 0
    assert metrics.in_degrees["file:2"] == 1
    assert metrics.in_degrees["class:1"] == 1
    assert metrics.in_degrees["isolated:1"] == 0
    assert metrics.out_degrees["isolated:1"] == 0
    assert metrics.edge_counts_by_type["imports"] == 1
    assert metrics.edge_counts_by_type["contains"] == 1
    assert metrics.node_counts_by_type["file"] == 3
    assert metrics.node_counts_by_type["class"] == 1
