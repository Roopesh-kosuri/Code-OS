"""test_architecture_diagrams.py — Unit and integration tests for Architecture Diagram Generator."""
from __future__ import annotations

import tempfile
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from app.features.ai.diagrams.code_analyzer import analyze_codebase
from app.features.ai.diagrams.mermaid_generator import (
    generate_api_diagram,
    generate_component_diagram,
    generate_data_flow_diagram,
    generate_entity_relationship,
    render_png,
    render_svg_preview,
    DIAGRAM_CACHE,
)
from app.main import app

client = TestClient(app)


def test_analyze_codebase_detects_components(tmp_path: Path):
    """Verify that analyze_codebase detects modules, classes, and functions in code files."""
    # Create sample Python file
    py_file = tmp_path / "user_service.py"
    py_file.write_text(
        """
class UserService:
    def get_user(self, user_id: str):
        return {"id": user_id}

    def create_user(self, data: dict):
        return {"id": "123", **data}
""",
        encoding="utf-8",
    )

    # Create sample TSX component file
    tsx_file = tmp_path / "UserProfile.tsx"
    tsx_file.write_text(
        """
import React from 'react';
import { fetchUser } from './user_service';

export const UserProfile = () => {
    return <div>User Profile</div>;
};
""",
        encoding="utf-8",
    )

    result = analyze_codebase(str(tmp_path))
    components = result["components"]

    assert len(components) == 2
    comp_names = {c["name"] for c in components}
    assert "user_service" in comp_names
    assert "UserProfile" in comp_names

    user_srv = next(c for c in components if c["name"] == "user_service")
    assert user_srv["language"] == "python"
    assert "UserService" in user_srv["classes"]
    assert "get_user" in user_srv["functions"]


def test_detects_import_relationships(tmp_path: Path):
    """Verify that import statements establish relationships between components."""
    service_file = tmp_path / "order_service.py"
    service_file.write_text(
        """
class OrderService:
    def process_order(self):
        pass
""",
        encoding="utf-8",
    )

    controller_file = tmp_path / "order_controller.py"
    controller_file.write_text(
        """
from order_service import OrderService

class OrderController:
    def __init__(self):
        self.service = OrderService()
""",
        encoding="utf-8",
    )

    result = analyze_codebase(str(tmp_path))
    relationships = result["relationships"]

    assert len(relationships) >= 1
    rel = next((r for r in relationships if r["source"] == "order_controller" and r["target"] == "order_service"), None)
    assert rel is not None
    assert rel["type"] in {"imports", "calls_service"}


def test_extracts_api_endpoints(tmp_path: Path):
    """Verify that FastAPI / Flask route decorators are parsed into API endpoints."""
    routes_file = tmp_path / "routes.py"
    routes_file.write_text(
        """
from fastapi import APIRouter

router = APIRouter()

@router.get("/api/users")
def get_users():
    return []

@router.post("/api/users/{user_id}/activate")
def activate_user(user_id: str):
    return {"status": "active"}
""",
        encoding="utf-8",
    )

    result = analyze_codebase(str(tmp_path))
    apis = result["apis"]

    assert len(apis) == 2
    paths = {a["path"] for a in apis}
    assert "/api/users" in paths
    assert "/api/users/{user_id}/activate" in paths

    get_route = next(a for a in apis if a["path"] == "/api/users")
    assert get_route["method"] == "GET"
    assert get_route["handler"] == "get_users"
    assert get_route["resource"] == "users"


def test_generate_component_diagram_valid_mermaid():
    """Verify generate_component_diagram produces valid Mermaid graph syntax."""
    components = [
        {"name": "AuthController", "type": "controller", "language": "python"},
        {"name": "AuthService", "type": "service", "language": "python"},
        {"name": "UserModel", "type": "model", "language": "python"},
    ]
    relationships = [
        {"source": "AuthController", "target": "AuthService", "label": "delegates to", "type": "calls_service"},
        {"source": "AuthService", "target": "UserModel", "label": "queries", "type": "uses_model"},
    ]

    diagram = generate_component_diagram(components, relationships)

    assert diagram.startswith("graph TD")
    assert "classDef controller" in diagram
    assert "AuthController" in diagram
    assert "AuthService" in diagram
    assert "UserModel" in diagram
    assert "-->" in diagram
    assert "delegates to" in diagram or "queries" in diagram


def test_generate_data_flow_diagram():
    """Verify generate_data_flow_diagram produces valid Mermaid flowchart syntax with flow layers."""
    apis = [
        {"method": "GET", "path": "/api/products", "handler": "list_products", "resource": "products"}
    ]
    models = [
        {"name": "Product", "type": "database_model", "fields": [{"name": "id", "type": "int"}]}
    ]

    diagram = generate_data_flow_diagram(apis, models)

    assert diagram.startswith("flowchart LR")
    assert "Client" in diagram
    assert "Router" in diagram
    assert "ServiceLayer" in diagram
    assert "Database" in diagram
    assert "list_products" in diagram
    assert "Product" in diagram


def test_export_diagram_as_png(tmp_path: Path):
    """Verify that diagrams can be exported and rendered as PNG images with valid PNG header."""
    svg = render_svg_preview("graph TD\n    A-->B", "component")
    png_bytes = render_png("test-diag-123", svg, "graph TD\n    A-->B")

    assert isinstance(png_bytes, bytes)
    assert len(png_bytes) > 0
    # PNG files must start with the standard 8-byte PNG magic header
    assert png_bytes[:8] == b"\x89PNG\r\n\x1a\n"

    # Also test export endpoint via API client
    from app.core.auth import get_token
    token = get_token()

    gen_res = client.post(
        "/api/diagrams/generate",
        json={"workspace": str(tmp_path), "type": "component"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert gen_res.status_code == 200
    diag_id = gen_res.json()["diagram_id"]

    export_res = client.get(
        f"/api/diagrams/export/{diag_id}?format=png",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert export_res.status_code == 200
    assert export_res.headers["content-type"] == "image/png"
    assert export_res.content[:8] == b"\x89PNG\r\n\x1a\n"
