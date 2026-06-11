from __future__ import annotations

import ast
from pathlib import Path


MODULE_G_FILES = [
    Path("backend/app/schemas/command.py"),
    Path("backend/app/sim/prompt_builder.py"),
    Path("backend/app/sim/llm_provider.py"),
    Path("backend/app/sim/command_parser.py"),
    Path("backend/app/sim/operator_decision.py"),
]


FORBIDDEN_IMPORTS = {
    "backend.app.sim.physics",
    "backend.app.sim.task_state_machine",
    "backend.app.schemas.control",
    "backend.app.schemas.state",
    "backend.app.sim.recorder",
    "backend.app.sim.weather",
    "backend.app.sim.layout",
}


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _imported_modules(tree: ast.AST) -> set[str]:
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imported.add(node.module)
    return imported


def test_module_g_files_do_not_import_simulation_side_effect_boundaries() -> None:
    for path in MODULE_G_FILES:
        tree = ast.parse(_source(path), filename=str(path))
        imported = _imported_modules(tree)

        assert not (imported & FORBIDDEN_IMPORTS), path


def test_module_g_files_do_not_call_persistence_write_apis() -> None:
    forbidden_calls = {
        "open",
        "write_text",
        "write_bytes",
        "dump",
        "dumps_to_file",
        "to_parquet",
        "to_csv",
    }

    for path in MODULE_G_FILES:
        tree = ast.parse(_source(path), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if isinstance(func, ast.Name):
                assert func.id not in forbidden_calls, f"{path}: {func.id}"
            elif isinstance(func, ast.Attribute):
                assert func.attr not in forbidden_calls, f"{path}: {func.attr}"


def test_module_g_static_text_has_no_forbidden_persisted_secret_field_names() -> None:
    for path in MODULE_G_FILES:
        source = _source(path)
        if path.name in {"command.py", "secret_resolver.py"}:
            continue
        for forbidden in [
            "resolved_full_api_key",
            "raw_api_key",
        ]:
            assert forbidden not in source, path


def test_module_g_public_files_keep_schema_version_constant() -> None:
    command_source = _source(Path("backend/app/schemas/command.py"))
    provider_source = _source(Path("backend/app/sim/llm_provider.py"))

    assert 'COMMAND_SCHEMA_VERSION = "1.0"' in command_source
    assert "COMMAND_SCHEMA_VERSION" in provider_source
