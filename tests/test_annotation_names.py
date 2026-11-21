"""An annotation name must be bound at module scope in its own module.

Every module here opens with ``from __future__ import annotations``, so an
annotation stays a string until a consumer resolves it. A name the module never
binds at module scope therefore costs nothing at import time, nothing in the
suite and nothing in CI -- and only the first resolver (``typing.get_type_hints``,
a schema generator, a type checker reading the source) sees the break. ``#1202``
found one (``Tuple``), ``#1203`` lists the rest.

The property pinned is static on purpose, and it is *module scope* only: names
that count are imports (``if TYPE_CHECKING:`` and ``try``/``except`` included --
they run at module scope), module-level assignments, ``def``/``class`` and
builtins. Neither a function body nor an enclosing function's parameters bind an
annotation name, because ``get_type_hints`` resolves against the function's
``__globals__``; ``import random`` inside a method is invisible to it. A class
body's own bindings do count for that class's attributes, since
``get_type_hints`` resolves those against ``vars(cls)`` too.

The test does **not** resolve annotations at runtime: that would demand real
imports of ``ParallelStrategy``, ``Invariant`` and ``VerifierBoost`` and
reintroduce the import cycles those strings exist to avoid.
"""

from __future__ import annotations

import ast
import builtins
import pathlib
import warnings

PACKAGE = pathlib.Path(__file__).resolve().parents[1] / "agentdescent"
BUILTINS = set(dir(builtins))
_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


def _scope_imports(nodes: list[ast.stmt]) -> set[str]:
    """Names imported while a statement list runs at module scope.

    Descends into the blocks that run there (``if``, ``try``, ``with``,
    ``for``, ``while``) and stops at every new scope: an import inside a
    function or class body binds that scope's locals, never the module.
    """
    names: set[str] = set()
    for node in nodes:
        if isinstance(node, _SCOPES):
            continue
        if isinstance(node, ast.Import):
            names |= {alias.asname or alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            names |= {
                alias.asname or alias.name
                for alias in node.names
                if alias.name != "*"
            }
        elif isinstance(node, (ast.If, ast.While, ast.For, ast.AsyncFor, ast.With, ast.AsyncWith)):
            names |= _scope_imports(node.body)
            names |= _scope_imports(getattr(node, "orelse", []))
        elif isinstance(node, ast.Try):
            names |= _scope_imports(node.body)
            names |= _scope_imports(node.orelse)
            names |= _scope_imports(node.finalbody)
            for handler in node.handlers:
                names |= _scope_imports(handler.body)
    return names


def _target_names(node: ast.AST) -> set[str]:
    if isinstance(node, ast.Name):
        return {node.id}
    if isinstance(node, (ast.Tuple, ast.List)):
        return set().union(*(_target_names(elt) for elt in node.elts))
    if isinstance(node, ast.Starred):
        return _target_names(node.value)
    return set()


def _block_bindings(nodes: list[ast.stmt]) -> set[str]:
    """Names this statement list binds at its own level, nested scopes excluded."""
    names: set[str] = set()
    for node in nodes:
        if isinstance(node, _SCOPES):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                names |= _target_names(target)
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
            names |= _target_names(node.target)
        elif isinstance(node, (ast.For, ast.AsyncFor)):
            names |= _target_names(node.target)
            names |= _block_bindings(node.body)
            names |= _block_bindings(node.orelse)
        elif isinstance(node, (ast.With, ast.AsyncWith)):
            for item in node.items:
                if item.optional_vars is not None:
                    names |= _target_names(item.optional_vars)
            names |= _block_bindings(node.body)
        elif isinstance(node, (ast.If, ast.While)):
            names |= _block_bindings(node.body)
            names |= _block_bindings(node.orelse)
        elif isinstance(node, ast.Try):
            names |= _block_bindings(node.body)
            names |= _block_bindings(node.orelse)
            names |= _block_bindings(node.finalbody)
            for handler in node.handlers:
                if handler.name:
                    names.add(handler.name)
                names |= _block_bindings(handler.body)
    return names


def _annotation_names(node: ast.AST) -> set[str]:
    """Names a (possibly string-shaped) annotation expression mentions."""
    if isinstance(node, ast.Name):
        return {node.id}
    if isinstance(node, ast.Attribute):
        return _annotation_names(node.value)
    if isinstance(node, ast.Subscript):
        head = node.value
        is_literal = (isinstance(head, ast.Name) and head.id == "Literal") or (
            isinstance(head, ast.Attribute) and head.attr == "Literal"
        )
        names = _annotation_names(head)
        elements = node.slice.elts if isinstance(node.slice, ast.Tuple) else [node.slice]
        if is_literal:  # ``Literal["a"]`` holds values, not type names
            return names
        for element in elements:
            names |= _annotation_names(element)
        return names
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        with warnings.catch_warnings():  # a forward ref may carry a regex "\w"
            warnings.simplefilter("ignore")
            try:
                parsed = ast.parse(node.value, mode="eval")
            except SyntaxError:
                return set()
        return _annotation_names(parsed.body)
    if isinstance(node, ast.BinOp):
        return _annotation_names(node.left) | _annotation_names(node.right)
    if isinstance(node, (ast.Tuple, ast.List)):
        return set().union(*(_annotation_names(elt) for elt in node.elts))
    if isinstance(node, ast.Starred):
        return _annotation_names(node.value)
    return set()


def _annotation_sites(
    nodes: list[ast.stmt],
    owner: str,
    local: set[str],
    sites: list[tuple[str, ast.AST, set[str]]],
    in_function: bool = False,
) -> None:
    """Collect ``(owner, annotation, bindings visible besides the module's)``.

    Only annotations something resolves against module globals are collected: a
    signature, a class attribute, a module-level variable. A local variable's
    annotation inside a function is skipped -- PEP 526 never evaluates it, and a
    reader resolves it in that function's own scope, where a local import counts.
    """
    for node in nodes:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            every = [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]
            every += [arg for arg in (node.args.vararg, node.args.kwarg) if arg is not None]
            for arg in every:
                if arg.annotation is not None:
                    sites.append((node.name, arg.annotation, set()))
            if node.returns is not None:
                sites.append((node.name, node.returns, set()))
            _annotation_sites(node.body, node.name, set(), sites, in_function=True)
        elif isinstance(node, ast.ClassDef):
            _annotation_sites(node.body, node.name, _block_bindings(node.body), sites, in_function)
        elif isinstance(node, ast.AnnAssign):
            if not in_function:
                sites.append((owner, node.annotation, local))
        elif isinstance(node, (ast.If, ast.While, ast.For, ast.AsyncFor, ast.With, ast.AsyncWith)):
            _annotation_sites(node.body, owner, local, sites, in_function)
            _annotation_sites(getattr(node, "orelse", []), owner, local, sites, in_function)
        elif isinstance(node, ast.Try):
            _annotation_sites(node.body, owner, local, sites, in_function)
            for handler in node.handlers:
                _annotation_sites(handler.body, owner, local, sites, in_function)
            _annotation_sites(node.orelse, owner, local, sites, in_function)
            _annotation_sites(node.finalbody, owner, local, sites, in_function)


def _module_bindings(source: str) -> set[str]:
    """Everything this module binds at module scope, builtins excluded."""
    with warnings.catch_warnings():  # a demo literal carries a regex "\w"
        warnings.simplefilter("ignore")
        tree = ast.parse(source)
    return _scope_imports(tree.body) | _block_bindings(tree.body)


def _imports_in_functions(source: str) -> set[str]:
    """Names the module imports only from inside a function body."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        tree = ast.parse(source)
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            for inner in ast.walk(node):
                if isinstance(inner, ast.ImportFrom):
                    found |= {alias.asname or alias.name for alias in inner.names}
                elif isinstance(inner, ast.Import):
                    found |= {alias.asname or alias.name.split(".")[0] for alias in inner.names}
    return found


def _type_checking_imports(source: str) -> set[str]:
    """Names the module imports under a module-level ``if TYPE_CHECKING:``."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        tree = ast.parse(source)
    found: set[str] = set()
    for node in tree.body:
        if not isinstance(node, ast.If):
            continue
        test = node.test
        if not (isinstance(test, ast.Name) and test.id == "TYPE_CHECKING"):
            continue
        found |= _scope_imports(node.body)
    return found


def _unbound_rows(source: str, module: str) -> dict[tuple[str, str], set[str]]:
    """``(module, name)`` -> owners, for every annotation name the module misses."""
    with warnings.catch_warnings():  # a demo literal carries a regex "\w"
        warnings.simplefilter("ignore")
        tree = ast.parse(source)
    module_bound = _module_bindings(source) | BUILTINS
    sites: list[tuple[str, ast.AST, set[str]]] = []
    _annotation_sites(tree.body, "<module>", set(), sites)

    rows: dict[tuple[str, str], set[str]] = {}
    for owner, annotation, local in sites:
        for name in _annotation_names(annotation):
            if name in module_bound or name in local:
                continue
            rows.setdefault((module, name), set()).add(owner)
    return rows


def _pairs(source: str, module: str) -> list[tuple[str, str]]:
    rows = _unbound_rows(source, module)
    return sorted(
        (f"{module}:{owner}", name) for (module, name), owners in rows.items() for owner in owners
    )


def test_module_scope_binding_rule_has_not_drifted() -> None:
    """The negative control: a function-local import binds nothing at module scope."""
    in_function = (
        "from __future__ import annotations\n"
        "from typing import Optional\n"
        "def go(extra: Optional['Hidden'] = None) -> None:\n"
        "    from .elsewhere import Hidden\n"
        "    return None\n"
    )
    assert _pairs(in_function, "m.py") == [
        ("m.py:go", "Hidden"),
    ], "a function-local import must not be credited"

    type_checking_only = (
        "from __future__ import annotations\n"
        "from typing import TYPE_CHECKING, Optional\n"
        "if TYPE_CHECKING:\n"
        "    from .elsewhere import Hidden\n"
        "def go(extra: Optional['Hidden'] = None) -> None:\n"
        "    return None\n"
    )
    assert _pairs(type_checking_only, "m.py") == [], "a TYPE_CHECKING import is module scope"


def _without_type_checking_blocks(source: str) -> str:
    tree = ast.parse(source)
    tree.body = [
        node
        for node in tree.body
        if not (isinstance(node, ast.If) and isinstance(node.test, ast.Name) and node.test.id == "TYPE_CHECKING")
    ]
    return ast.unparse(tree)


def test_the_real_modules_pin_the_same_rule() -> None:
    """The rule against the real files it was written for, not just a snippet."""
    async_source = (PACKAGE / "async_evolve.py").read_text(encoding="utf-8")
    stripped = _without_type_checking_blocks(async_source)
    assert "EvolvingArtifact" in _imports_in_functions(stripped), "the file imports it in a function"
    assert "EvolvingArtifact" not in _module_bindings(stripped), "that import must credit nothing"

    settings_source = (PACKAGE / "evolve_settings.py").read_text(encoding="utf-8")
    assert "RoundInfo" in _type_checking_imports(settings_source), "the TYPE_CHECKING block names it"
    assert "RoundInfo" in _module_bindings(settings_source), "TYPE_CHECKING is module scope"
    assert "RoundInfo" not in _imports_in_functions(settings_source), "and it is not function-local"


def test_every_annotation_name_is_bound() -> None:
    pairs: list[tuple[str, str]] = []
    for path in sorted(PACKAGE.rglob("*.py")):
        module = path.relative_to(PACKAGE.parent).as_posix()
        pairs += _pairs(path.read_text(encoding="utf-8"), module)
    report = "\n".join(f"  {owner} -> {name}" for owner, name in pairs)
    assert not pairs, (
        f"annotation names nothing binds at module scope ({len(pairs)} sites):\n" + report
    )
