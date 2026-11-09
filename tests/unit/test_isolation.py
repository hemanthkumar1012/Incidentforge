"""Static checks on the separation between the shop, the lab and (later) the investigator."""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _imports(pkg: str) -> set[str]:
    names: set[str] = set()
    for path in (ROOT / pkg).rglob("*.py"):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                names.add(node.module.split(".")[0])
    return names


def test_shop_does_not_import_lab():
    assert "lab" not in _imports("shop")


def test_forge_does_not_import_lab():
    assert "lab" not in _imports("forge")


def test_forge_image_excludes_lab_and_scenarios():
    dockerfile = (ROOT / "Dockerfile").read_text()
    forge_stage = dockerfile.split("AS forge")[1].split("FROM ")[0]
    assert "COPY lab" not in forge_stage
    assert "scenarios" not in forge_stage


def test_scripted_provider_not_reachable_from_wiring():
    wiring = (ROOT / "forge" / "wiring.py").read_text()
    assert "providers.scripted" not in wiring and "ScriptedProvider" not in wiring


def test_shop_image_excludes_lab_code():
    dockerfile = (ROOT / "Dockerfile").read_text()
    shop_stage = dockerfile.split("FROM shop AS lab")[0]
    assert "COPY lab" not in shop_stage


def test_no_ground_truth_outside_lab():
    for path in ROOT.rglob("*.py"):
        rel = path.relative_to(ROOT)
        if rel.parts[0] in {"lab", "tests"}:
            continue
        assert "ground_truth" not in path.read_text(), f"{rel} references ground_truth"
