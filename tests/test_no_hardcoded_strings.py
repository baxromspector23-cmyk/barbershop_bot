from __future__ import annotations

import ast
import os
import re
from pathlib import Path


def test_no_hardcoded_strings_in_handlers():
    """Q2 AST audit: No literal strings containing letters directly in answer/edit_text/send_message/send_invoice."""
    handlers_dir = Path("app/handlers")
    letter_re = re.compile(r"[a-zA-Z\u0400-\u04FF]")
    target_methods = {"answer", "edit_text", "send_message", "send_invoice"}

    violations: list[str] = []

    for py_file in handlers_dir.glob("*.py"):
        with open(py_file, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=str(py_file))

        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func_name = None
                if isinstance(node.func, ast.Name):
                    func_name = node.func.id
                elif isinstance(node.func, ast.Attribute):
                    func_name = node.func.attr

                if func_name in target_methods:
                    candidate = None
                    if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                        candidate = node.args[0].value
                    for kw in node.keywords:
                        if kw.arg == "text" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                            candidate = kw.value.value

                    if candidate and letter_re.search(candidate):
                        # Truncate for clean error report
                        snippet = candidate.strip().replace("\n", " ")[:60]
                        violations.append(f"{py_file.name}:{node.lineno} in {func_name}(): '{snippet}'")

    assert not violations, (
        f"Found {len(violations)} hardcoded strings in handlers that should use t(...):\n"
        + "\n".join(f"  - {v}" for v in violations)
    )
