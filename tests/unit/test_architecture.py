import ast
from pathlib import Path

FORBIDDEN_ROOTS = {
    "azure",
    "boto3",
    "fastapi",
    "flask",
    "google",
    "homeassistant",
    "mcp",
    "openai",
    "sqlalchemy",
}


def test_domain_has_no_application_dependencies() -> None:
    source_root = Path(__file__).parents[2] / "src" / "italian_energy" / "domain"
    for path in source_root.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name.split(".")[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module.split(".")[0]]
            else:
                continue
            assert FORBIDDEN_ROOTS.isdisjoint(names), f"forbidden import in {path}: {names}"
