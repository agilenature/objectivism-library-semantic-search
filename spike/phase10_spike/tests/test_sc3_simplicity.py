"""SC3 simplicity measurement: recovery code <= transition code (GA-9).

Proves that the RecoveryCrawler is demonstrably simpler than the
ResetTransitionManager it compensates for:
  1. Fewer non-blank, non-comment lines
  2. Zero retry loops (no 'while' keyword in recovery code)
"""

import ast
import os

import pytest


def _count_class_lines(file_path: str, class_name: str) -> int:
    """Count non-blank, non-comment lines in a class body.

    Uses ast.parse to accurately locate the class, then counts
    meaningful lines (excluding blanks, comments, and docstrings).
    """
    with open(file_path) as f:
        source = f.read()

    tree = ast.parse(source)

    # Find the class node
    class_node = None
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            class_node = node
            break

    if class_node is None:
        raise ValueError(f"Class {class_name} not found in {file_path}")

    # Get line range for the class
    start_line = class_node.lineno
    end_line = class_node.end_lineno
    lines = source.splitlines()[start_line - 1 : end_line]

    # Count non-blank, non-comment lines (excluding docstrings)
    count = 0
    in_docstring = False
    for line in lines:
        stripped = line.strip()
        # Track triple-quote docstrings
        if '"""' in stripped or "'''" in stripped:
            quote = '"""' if '"""' in stripped else "'''"
            occurrences = stripped.count(quote)
            if occurrences == 1:
                in_docstring = not in_docstring
                continue  # Skip docstring boundary lines
            elif occurrences >= 2:
                continue  # Single-line docstring
        if in_docstring:
            continue
        if not stripped:
            continue
        if stripped.startswith("#"):
            continue
        count += 1

    return count


def test_recovery_simpler_than_transition():
    """SC3: RecoveryCrawler has fewer lines than ResetTransitionManager and no retry loops."""
    spike_dir = os.path.join(
        os.path.dirname(__file__), os.pardir
    )
    recovery_path = os.path.join(spike_dir, "recovery_crawler.py")
    transition_path = os.path.join(spike_dir, "transition_reset.py")

    recovery_lines = _count_class_lines(recovery_path, "RecoveryCrawler")
    transition_lines = _count_class_lines(transition_path, "ResetTransitionManager")

    print(f"\nSC3 Measurement:")
    print(f"  RecoveryCrawler lines:        {recovery_lines}")
    print(f"  ResetTransitionManager lines:  {transition_lines}")
    print(f"  Recovery <= Transition:         {recovery_lines <= transition_lines}")

    assert recovery_lines <= transition_lines, (
        f"Recovery ({recovery_lines} lines) should be <= "
        f"transition ({transition_lines} lines)"
    )

    # Verify no retry loops in recovery code
    with open(recovery_path) as f:
        recovery_source = f.read()

    assert "while " not in recovery_source, (
        "RecoveryCrawler should have no 'while' loops (GA-9: linear step resumption)"
    )
    print(f"  No 'while' loops in recovery:  True")
