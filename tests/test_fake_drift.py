"""Signature-parity guard for hand-written test fakes vs real API wrappers."""
from __future__ import annotations

import importlib
import importlib.util
import inspect
from pathlib import Path
from typing import Any

import pytest

# (fake_module_path, fake_class_name, real_module, real_class_name)
PAIRS = [
    ("test_gmail_server", "FakeAPI", "gmail_cli.api", "GmailAPI"),
    ("test_gmail_server", "FakeAPI", "google_workspace_mcp.gmail.changes_api", "GmailChangesAPI"),
]


def _load_fake_class(module_stem: str, class_name: str) -> type:
    path = Path(__file__).with_name(f"{module_stem}.py")
    spec = importlib.util.spec_from_file_location(module_stem, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return getattr(module, class_name)


def _load_class(module_path: str, class_name: str) -> type:
    module = importlib.import_module(module_path)
    return getattr(module, class_name)


def _fake_methods(fake_cls: type) -> list[tuple[str, Any]]:
    methods: list[tuple[str, Any]] = []
    for name, attr in vars(fake_cls).items():
        if name.startswith("_") or name == "__init__":
            continue
        if callable(attr):
            methods.append((name, attr))
    return methods


def _param_names(sig: inspect.Signature) -> set[str]:
    return set(sig.parameters.keys())


def _required_params(sig: inspect.Signature) -> set[str]:
    required: set[str] = set()
    for name, param in sig.parameters.items():
        if name == "self":
            continue
        if param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            continue
        if param.default is inspect.Parameter.empty:
            required.add(name)
    return required


def _real_has_var_keyword(sig: inspect.Signature) -> bool:
    return any(
        p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()
    )


def _check_pair(
    fake_module: str,
    fake_name: str,
    real_module: str,
    real_name: str,
) -> list[str]:
    fake_cls = _load_fake_class(fake_module, fake_name)
    real_cls = _load_class(real_module, real_name)
    errors: list[str] = []

    for method_name, fake_fn in _fake_methods(fake_cls):
        if not hasattr(real_cls, method_name):
            # Fake may implement server features ahead of the pinned sibling release.
            continue

        real_fn = getattr(real_cls, method_name)
        if not callable(real_fn):
            errors.append(f"{real_name}.{method_name} exists but is not callable")
            continue

        fake_sig = inspect.signature(fake_fn)
        real_sig = inspect.signature(real_fn)
        fake_params = _param_names(fake_sig) - {"self"}
        real_params = _param_names(real_sig) - {"self"}

        if not _real_has_var_keyword(real_sig):
            unknown = fake_params - real_params
            for param in sorted(unknown):
                errors.append(
                    f"{fake_name}.{method_name} has parameter '{param}' "
                    f"unknown to {real_name}.{method_name}"
                )

        missing_required = _required_params(real_sig) - fake_params
        for param in sorted(missing_required):
            errors.append(
                f"{fake_name}.{method_name} missing required parameter '{param}' "
                f"from {real_name}.{method_name}"
            )

    return errors


@pytest.mark.parametrize(
    "fake_module,fake_name,real_module,real_name",
    PAIRS,
    ids=[f"{p[1]}↔{p[3]}" for p in PAIRS],
)
def test_fake_signature_parity(fake_module, fake_name, real_module, real_name):
    errors = _check_pair(fake_module, fake_name, real_module, real_name)
    assert not errors, "Fake/wrapper signature drift:\n" + "\n".join(f"  - {e}" for e in errors)
