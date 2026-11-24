"""Guards against SQL injection: SQL text may be built dynamically only from a short list of trusted names
(placeholder style, table/column constants). User input must always go through `?` / `%s` parameters."""
import ast
import glob
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FILES = [os.path.join(ROOT, f) for f in ("app.py", "exports.py", "farm_tasks.py", "forecast.py", "vision.py")]
FILES += glob.glob(os.path.join(ROOT, "routes", "*.py"))

# names allowed inside f-strings / concatenations that build SQL (all are constants or placeholders, never request data)
TRUSTED = {"ph", "t", "table", "col", "definition", "cols", "args", "yr"}   # yr = " AND substr(..)=<placeholder>" fragment; the year itself is a parameter


def _is_sql_call(node):
    return (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr in ("execute", "executemany") and node.args)


def _names(expr):
    return {n.id for n in ast.walk(expr) if isinstance(n, ast.Name)}


def test_dynamic_sql_uses_only_trusted_names():
    bad = []
    for path in FILES:
        tree = ast.parse(open(path, encoding="utf-8").read())
        for node in ast.walk(tree):
            if not _is_sql_call(node):
                continue
            first = node.args[0]
            dynamic = isinstance(first, ast.JoinedStr) or (isinstance(first, ast.BinOp) and isinstance(first.op, (ast.Add, ast.Mod))) \
                or (isinstance(first, ast.Call) and isinstance(first.func, ast.Attribute) and first.func.attr == "format")
            if dynamic:
                if isinstance(first, ast.JoinedStr):
                    used = {n.id for v in first.values if isinstance(v, ast.FormattedValue) for n in ast.walk(v.value) if isinstance(n, ast.Name)}
                else:
                    used = _names(first)
                extra = used - TRUSTED
                if extra:
                    bad.append((os.path.relpath(path, ROOT), node.lineno, sorted(extra)))
    assert not bad, f"SQL built from untrusted-looking names (use ? parameters): {bad}"
