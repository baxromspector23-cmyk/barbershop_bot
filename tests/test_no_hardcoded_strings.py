from __future__ import annotations

import ast
import re
from pathlib import Path


class _HandlerStringAuditor(ast.NodeVisitor):
    def __init__(self, filename: str, letter_re: re.Pattern, target_methods: set[str]):
        self.filename = filename
        self.letter_re = letter_re
        self.target_methods = target_methods
        self.violations: list[str] = []
        self.func_scopes: dict[str, dict[str, list[ast.AST]]] = {}
        self.func_returns: dict[str, list[ast.AST]] = {}
        self.current_func: str | None = None

    def _lookup_assign(self, name: str, func_name: str | None) -> list[ast.AST]:
        if func_name and func_name in self.func_scopes:
            return self.func_scopes[func_name].get(name, [])
        return []

    def visit_FunctionDef(self, node: ast.FunctionDef):
        prev = self.current_func
        self.current_func = node.name
        self.func_scopes[node.name] = {}
        for stmt in node.body:
            if isinstance(stmt, ast.Return) and stmt.value:
                ret_val = stmt.value
                if isinstance(ret_val, ast.Tuple) and ret_val.elts:
                    self.func_returns.setdefault(node.name, []).append((node.name, ret_val.elts[0]))
                else:
                    self.func_returns.setdefault(node.name, []).append((node.name, ret_val))
        self.generic_visit(node)
        self.current_func = prev

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
        prev = self.current_func
        self.current_func = node.name
        self.func_scopes[node.name] = {}
        for stmt in node.body:
            if isinstance(stmt, ast.Return) and stmt.value:
                ret_val = stmt.value
                if isinstance(ret_val, ast.Tuple) and ret_val.elts:
                    self.func_returns.setdefault(node.name, []).append((node.name, ret_val.elts[0]))
                else:
                    self.func_returns.setdefault(node.name, []).append((node.name, ret_val))
        self.generic_visit(node)
        self.current_func = prev

    def visit_Assign(self, node: ast.Assign):
        if self.current_func:
            scope = self.func_scopes[self.current_func]
            for target in node.targets:
                if isinstance(target, ast.Name):
                    scope.setdefault(target.id, []).append(node.value)
                elif isinstance(target, ast.Tuple):
                    for elt in target.elts:
                        if isinstance(elt, ast.Name):
                            scope.setdefault(elt.id, []).append(node.value)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign):
        if self.current_func and isinstance(node.target, ast.Name) and node.value:
            self.func_scopes[self.current_func].setdefault(node.target.id, []).append(node.value)
        self.generic_visit(node)

    def _extract_literals(self, node: ast.AST, func_name: str | None, depth: int = 0) -> list[str]:
        if depth > 6:
            return []
        found: list[str] = []

        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            cleaned = re.sub(r"<[^>]+>", "", node.value).strip()
            # Ignore technical language tags, punctuation, or short tokens
            if self.letter_re.search(cleaned) and cleaned not in {"uz", "ru", "uz_cyrl", "HTML", "Markdown"}:
                found.append(node.value)

        elif isinstance(node, ast.JoinedStr):
            for part in node.values:
                if isinstance(part, ast.Constant) and isinstance(part.value, str):
                    cleaned = re.sub(r"<[^>]+>", "", part.value).strip()
                    if self.letter_re.search(cleaned):
                        found.append(part.value)
                elif isinstance(part, ast.FormattedValue) and isinstance(part.value, ast.Name):
                    for val_node in self._lookup_assign(part.value.id, func_name):
                        found.extend(self._extract_literals(val_node, func_name, depth + 1))

        elif isinstance(node, ast.Name):
            for val_node in self._lookup_assign(node.id, func_name):
                found.extend(self._extract_literals(val_node, func_name, depth + 1))

        elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            found.extend(self._extract_literals(node.left, func_name, depth + 1))
            found.extend(self._extract_literals(node.right, func_name, depth + 1))

        elif isinstance(node, ast.IfExp):
            found.extend(self._extract_literals(node.body, func_name, depth + 1))
            found.extend(self._extract_literals(node.orelse, func_name, depth + 1))

        elif isinstance(node, ast.Await) and isinstance(node.value, ast.Call):
            call_node = node.value
            callee = getattr(call_node.func, "id", getattr(call_node.func, "attr", None))
            if callee and callee in self.func_returns:
                for origin_func, ret_expr in self.func_returns[callee]:
                    found.extend(self._extract_literals(ret_expr, origin_func, depth + 1))

        elif isinstance(node, ast.Call):
            callee = getattr(node.func, "id", getattr(node.func, "attr", None))
            if callee and callee in self.func_returns:
                for origin_func, ret_expr in self.func_returns[callee]:
                    found.extend(self._extract_literals(ret_expr, origin_func, depth + 1))
            elif getattr(node.func, "attr", None) == "get":
                # For dict.get('key', default), only inspect default (args[1]) if present
                if len(node.args) >= 2:
                    found.extend(self._extract_literals(node.args[1], func_name, depth + 1))
            elif callee not in {"t", "format_money"}:
                for arg in node.args:
                    found.extend(self._extract_literals(arg, func_name, depth + 1))

        elif isinstance(node, ast.List):
            for elt in node.elts:
                found.extend(self._extract_literals(elt, func_name, depth + 1))

        return found

    def visit_Call(self, node: ast.Call):
        func_name = getattr(node.func, "id", getattr(node.func, "attr", None))

        if func_name in self.target_methods:
            candidates: list[ast.AST] = []
            if func_name in {"answer", "edit_text"}:
                if node.args:
                    candidates.append(node.args[0])
            elif func_name in {"send_message", "send_invoice"}:
                if len(node.args) >= 2:
                    candidates.append(node.args[1])
                elif node.args:
                    candidates.append(node.args[0])

            for kw in node.keywords:
                if kw.arg in {"text", "caption", "title", "description"}:
                    candidates.append(kw.value)

            for cand in candidates:
                literals = self._extract_literals(cand, self.current_func)
                for lit in literals:
                    snippet = lit.strip().replace("\n", " ")[:60]
                    self.violations.append(f"{self.filename}:{node.lineno} in {func_name}(): '{snippet}'")

        self.generic_visit(node)


def test_no_hardcoded_strings_in_handlers():
    """AST audit: No literal strings or f-strings (JoinedStr) in answer/edit_text/send_message/send_invoice,

    including strings assigned to local variables and then passed to these methods.
    """
    scan_dirs = [Path("app/handlers"), Path("app/services")]
    letter_re = re.compile(r"[a-zA-Z\u0400-\u04FF]")
    target_methods = {"answer", "edit_text", "send_message", "send_invoice"}

    violations: list[str] = []

    for scan_dir in scan_dirs:
        for py_file in sorted(scan_dir.glob("*.py")):
            with open(py_file, "r", encoding="utf-8") as f:
                tree = ast.parse(f.read(), filename=str(py_file))

            auditor = _HandlerStringAuditor(py_file.name, letter_re, target_methods)
            auditor.visit(tree)
            violations.extend(auditor.violations)

    assert not violations, (
        f"Found {len(violations)} hardcoded strings in handlers/services that should use t(...):\n"
        + "\n".join(f"  - {v}" for v in violations)
    )
