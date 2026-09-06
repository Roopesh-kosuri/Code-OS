"""mermaid_generator.py — Converts code analysis into interactive Mermaid diagrams.

Generates:
1. Component Diagrams (graph TD / flowchart TB)
2. Data Flow Diagrams (flowchart LR / TD)
3. API Sequence Diagrams (sequenceDiagram)
4. Entity Relationship Diagrams (erDiagram)
5. Dark theme SVG & PNG preview renderers
"""
from __future__ import annotations

import html
import io
import logging
import re
import uuid
from typing import Any, Dict, List, Optional, Tuple
from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

# Diagram cache: diagram_id -> { "type": str, "code": str, "svg": str, "png": bytes }
DIAGRAM_CACHE: Dict[str, Dict[str, Any]] = {}


def _sanitize_id(name: str) -> str:
    """Sanitize string to valid Mermaid node ID."""
    clean = re.sub(r"[^a-zA-Z0-9_]", "_", name)
    if clean and clean[0].isdigit():
        clean = "node_" + clean
    return clean or "node"


def generate_component_diagram(
    components: List[Dict[str, Any]], relationships: List[Dict[str, Any]]
) -> str:
    """Generate Mermaid syntax for Component Architecture diagram."""
    lines: List[str] = [
        "graph TD",
        "    %% Architecture Component Diagram",
        "    classDef controller fill:#0f172a,stroke:#38bdf8,stroke-width:2px,color:#f8fafc;",
        "    classDef service fill:#0f172a,stroke:#a855f7,stroke-width:2px,color:#f8fafc;",
        "    classDef model fill:#0f172a,stroke:#10b981,stroke-width:2px,color:#f8fafc;",
        "    classDef ui fill:#0f172a,stroke:#f59e0b,stroke-width:2px,color:#f8fafc;",
        "    classDef store fill:#0f172a,stroke:#ec4899,stroke-width:2px,color:#f8fafc;",
        "    classDef module fill:#0f172a,stroke:#64748b,stroke-width:2px,color:#f8fafc;",
    ]

    # Group components by type into subgraphs
    grouped: Dict[str, List[Dict[str, Any]]] = {
        "ui_component": [],
        "store": [],
        "controller": [],
        "service": [],
        "model": [],
        "module": [],
    }

    subgraph_titles = {
        "ui_component": "Frontend Views & Components",
        "store": "State Management & Stores",
        "controller": "API Routes & Controllers",
        "service": "Business Logic & Services",
        "model": "Models & Data Layer",
        "module": "Utilities & Modules",
    }

    # Limit components to top 40 to ensure Mermaid renders cleanly without crashing browser
    displayed_components = components[:40] if len(components) > 40 else components
    displayed_names = {c["name"] for c in displayed_components}

    for comp in displayed_components:
        c_type = comp.get("type", "module")
        if c_type not in grouped:
            grouped["module"].append(comp)
        else:
            grouped[c_type].append(comp)

    # Render Subgraphs
    for group_key, comp_list in grouped.items():
        if not comp_list:
            continue
        title = subgraph_titles.get(group_key, group_key.capitalize())
        lines.append(f"    subgraph {group_key}_subgraph [\"{title}\"]")
        for comp in comp_list:
            node_id = _sanitize_id(comp["name"])
            node_label = f"{comp['name']}\\n({comp.get('language', 'code')})"
            lines.append(f"        {node_id}[\"{node_label}\"]:::{group_key if group_key in {'controller', 'service', 'model', 'store', 'module'} else 'ui'}")
        lines.append("    end")

    # Render Relationships
    seen_edges = set()
    for rel in relationships:
        src = rel.get("source")
        tgt = rel.get("target")
        if src in displayed_names and tgt in displayed_names:
            src_id = _sanitize_id(src)
            tgt_id = _sanitize_id(tgt)
            edge_key = f"{src_id}->{tgt_id}"
            if edge_key not in seen_edges and src_id != tgt_id:
                seen_edges.add(edge_key)
                label = rel.get("label", "depends on")
                lines.append(f"    {src_id} -->|{label}| {tgt_id}")

    # Fallback if no relationships
    if not seen_edges and len(displayed_components) > 1:
        c1 = _sanitize_id(displayed_components[0]["name"])
        c2 = _sanitize_id(displayed_components[1]["name"])
        lines.append(f"    {c1} -->|delegates to| {c2}")

    return "\n".join(lines)


def generate_data_flow_diagram(
    apis: List[Dict[str, Any]], models: List[Dict[str, Any]]
) -> str:
    """Generate Mermaid syntax for Data Flow architecture diagram."""
    lines: List[str] = [
        "flowchart LR",
        "    %% Data Flow Architecture Diagram",
        "    classDef client fill:#1e1b4b,stroke:#818cf8,stroke-width:2px,color:#f8fafc;",
        "    classDef router fill:#082f49,stroke:#38bdf8,stroke-width:2px,color:#f8fafc;",
        "    classDef service fill:#3b0764,stroke:#c084fc,stroke-width:2px,color:#f8fafc;",
        "    classDef storage fill:#064e3b,stroke:#34d399,stroke-width:2px,color:#f8fafc;",
        "",
        "    Client([\"🌐 Web Client / IDE UI\"]):::client",
        "    Router[\"🔀 API Gateway & Router\"]:::router",
        "    ServiceLayer[\"⚙️ Business Logic & Services\"]:::service",
        "    Database[(\"🗄️ Database & Models\")]:::storage",
        "",
        "    Client -->|\"HTTP Request\\n(JSON Payload)\"| Router",
        "    Router -->|\"Validate & Route\\n(Pydantic/Schema)\"| ServiceLayer",
        "    ServiceLayer -->|\"Query / Persist\\n(SQL / ORM)\"| Database",
        "    Database -.->|\"Result Sets / Records\"| ServiceLayer",
        "    ServiceLayer -.->|\"Response DTO\"| Router",
        "    Router -.->|\"HTTP 200 OK\\n(JSON Response)\"| Client",
    ]

    # Add concrete API flow endpoints if detected
    top_apis = apis[:6] if apis else []
    if top_apis:
        lines.append("")
        lines.append("    subgraph DetectedEndpoints [\"Active API Flow\"]")
        for i, api in enumerate(top_apis):
            api_id = f"api_flow_{i}"
            method = api.get("method", "GET")
            path = api.get("path", "/api")
            handler = api.get("handler", "handler")
            lines.append(f"        {api_id}[\"{method} {path}\\n-> {handler}()\"]:::router")
        lines.append("    end")
        lines.append("    Router -.-> DetectedEndpoints")

    # Add concrete Models if detected
    top_models = models[:6] if models else []
    if top_models:
        lines.append("")
        lines.append("    subgraph DataEntities [\"Persisted Entities\"]")
        for j, mod in enumerate(top_models):
            mod_id = f"entity_{j}"
            name = mod.get("name", "Model")
            lines.append(f"        {mod_id}[(\"{name} Model\")]:::storage")
        lines.append("    end")
        lines.append("    Database -.-> DataEntities")

    return "\n".join(lines)


def generate_api_diagram(endpoints: List[Dict[str, Any]]) -> str:
    """Generate Mermaid sequence diagram for API endpoints."""
    lines: List[str] = [
        "sequenceDiagram",
        "    autonumber",
        "    actor Client as 🌐 Client (Frontend)",
        "    participant Gateway as 🔀 API Router",
        "    participant Service as ⚙️ Service Logic",
        "    participant Database as 🗄️ Database / State",
        "",
    ]

    # Pick up to 4 representative endpoints
    selected_apis = endpoints[:4] if endpoints else [
        {"method": "GET", "path": "/api/system/health", "handler": "health_check"},
        {"method": "POST", "path": "/api/ai/generate", "handler": "generate_completion"},
    ]

    for api in selected_apis:
        method = api.get("method", "GET")
        path = api.get("path", "/api/resource")
        handler = api.get("handler", "handler")

        lines.append(f"    %% Flow for {method} {path}")
        lines.append(f"    Client->>+Gateway: {method} {path}")
        lines.append(f"    Gateway->>+Service: {handler}(request_context)")
        if method in {"POST", "PUT", "PATCH", "DELETE"}:
            lines.append("    Service->>+Database: INSERT / UPDATE / DELETE query")
            lines.append("    Database-->>-Service: Acknowledge transaction commit")
        else:
            lines.append("    Service->>+Database: SELECT query")
            lines.append("    Database-->>-Service: Record results")
        lines.append("    Service-->>-Gateway: Result payload (DTO)")
        lines.append("    Gateway-->>-Client: 200 OK (application/json)")
        lines.append("")

    return "\n".join(lines)


def generate_entity_relationship(models: List[Dict[str, Any]]) -> str:
    """Generate Mermaid ER diagram for database models."""
    lines: List[str] = [
        "erDiagram",
        "    %% Entity Relationship Diagram",
    ]

    displayed_models = models[:15] if models else []
    if not displayed_models:
        # Default placeholder ER if no models detected
        lines.extend([
            "    WORKSPACE ||--o{ FILE : contains",
            "    FILE ||--o{ CHAT_SESSION : references",
            "    CHAT_SESSION ||--|{ MESSAGE : has",
            "    WORKSPACE {",
            "        string id PK",
            "        string name",
            "        string path",
            "    }",
            "    FILE {",
            "        string path PK",
            "        string extension",
            "        int size",
            "    }",
            "    CHAT_SESSION {",
            "        string id PK",
            "        string title",
            "        datetime created_at",
            "    }",
            "    MESSAGE {",
            "        string id PK",
            "        string role",
            "        string content",
            "    }",
        ])
        return "\n".join(lines)

    # Output entities
    model_names = {m["name"].upper() for m in displayed_models}
    for mod in displayed_models:
        m_name = mod["name"].upper()
        lines.append(f"    {m_name} {{")
        fields = mod.get("fields", [])
        if not fields:
            lines.append("        string id PK")
            lines.append("        string name")
        else:
            for f in fields[:8]:
                f_name = f.get("name", "field")
                f_type = f.get("type", "string").lower()
                is_pk = "PK" if f_name.lower() in {"id", "uuid", "pk"} else ""
                lines.append(f"        {f_type} {f_name} {is_pk}".strip())
        lines.append("    }")

    # Output relationships
    has_rel = False
    for mod in displayed_models:
        src = mod["name"].upper()
        for fk in mod.get("foreign_keys", []):
            tgt = fk.get("target", "").upper()
            if tgt in model_names and tgt != src:
                lines.append(f"    {tgt} ||--o{{ {src} : \"{fk.get('field', 'references')}\"")
                has_rel = True

    if not has_rel and len(displayed_models) > 1:
        m1 = displayed_models[0]["name"].upper()
        m2 = displayed_models[1]["name"].upper()
        lines.append(f"    {m1} ||--o{{ {m2} : references")

    return "\n".join(lines)


def render_svg_preview(diagram_code: str, diagram_type: str) -> str:
    """Generate dark-theme SVG representation of the diagram."""
    # Build clean SVG with CODE OS Dark Aesthetics
    width = 960
    height = 560
    title_map = {
        "component": "Architecture Component Diagram",
        "data_flow": "Data Flow Architecture Diagram",
        "api": "API Sequence Diagram",
        "er": "Entity Relationship Diagram",
    }
    title = title_map.get(diagram_type, "Architecture Diagram")

    # Extract some node labels from diagram_code for SVG visualization
    node_matches = re.findall(r'\["([^"]+)"\]', diagram_code)
    nodes = [html.escape(n.replace("\\n", " - ")) for n in node_matches[:12]]
    if not nodes:
        nodes = ["Client UI", "API Gateway", "Auth Controller", "Data Service", "Database"]

    svg_elements: List[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="100%" height="100%" style="background:#090d16; font-family:Inter,system-ui,sans-serif;">',
        '  <defs>',
        '    <linearGradient id="bgGrad" x1="0%" y1="0%" x2="100%" y2="100%">',
        '      <stop offset="0%" stop-color="#0b1120" />',
        '      <stop offset="100%" stop-color="#020617" />',
        '    </linearGradient>',
        '    <linearGradient id="cyanGrad" x1="0%" y1="0%" x2="100%" y2="0%">',
        '      <stop offset="0%" stop-color="#06b6d4" />',
        '      <stop offset="100%" stop-color="#3b82f6" />',
        '    </linearGradient>',
        '    <linearGradient id="purpleGrad" x1="0%" y1="0%" x2="100%" y2="0%">',
        '      <stop offset="0%" stop-color="#8b5cf6" />',
        '      <stop offset="100%" stop-color="#ec4899" />',
        '    </linearGradient>',
        '    <filter id="glow" x="-20%" y="-20%" width="140%" height="140%">',
        '      <feGaussianBlur stdDeviation="6" result="blur" />',
        '      <feComposite in="SourceGraphic" in2="blur" operator="over" />',
        '    </filter>',
        '  </defs>',
        f'  <rect width="{width}" height="{height}" fill="url(#bgGrad)" rx="12" stroke="#1e293b" stroke-width="1.5" />',
        f'  <text x="32" y="44" fill="#f8fafc" font-size="20" font-weight="700" letter-spacing="-0.02em">{title}</text>',
        '  <text x="32" y="68" fill="#94a3b8" font-size="12">CODE OS Architecture Generator • Local AST Analysis</text>',
        '  <line x1="32" y1="84" x2="928" y2="84" stroke="#1e293b" stroke-width="1" />',
    ]

    # Draw diagram preview cards based on extracted nodes
    cols = 3
    card_w = 260
    card_h = 80
    start_x = 48
    start_y = 110
    gap_x = 44
    gap_y = 36

    for idx, name in enumerate(nodes):
        row = idx // cols
        col = idx % cols
        x = start_x + col * (card_w + gap_x)
        y = start_y + row * (card_h + gap_y)
        if y + card_h > height - 60:
            break

        stroke_color = "#38bdf8" if idx % 3 == 0 else ("#c084fc" if idx % 3 == 1 else "#34d399")
        badge_text = "Controller" if idx % 3 == 0 else ("Service" if idx % 3 == 1 else "Model")

        svg_elements.extend([
            f'  <g transform="translate({x},{y})">',
            f'    <rect width="{card_w}" height="{card_h}" rx="8" fill="#0f172a" stroke="{stroke_color}" stroke-width="1.5" opacity="0.95" />',
            f'    <rect x="12" y="14" width="70" height="18" rx="4" fill="{stroke_color}" fill-opacity="0.15" />',
            f'    <text x="47" y="27" fill="{stroke_color}" font-size="10" font-weight="600" text-anchor="middle">{badge_text}</text>',
            f'    <text x="12" y="52" fill="#f1f5f9" font-size="13" font-weight="600">{name[:28]}</text>',
            '  </g>',
        ])

        # Draw connecting line to next
        if col < cols - 1 and idx + 1 < len(nodes):
            conn_x1 = x + card_w
            conn_y1 = y + card_h // 2
            conn_x2 = conn_x1 + gap_x
            conn_y2 = conn_y1
            svg_elements.append(
                f'  <line x1="{conn_x1}" y1="{conn_y1}" x2="{conn_x2}" y2="{conn_y2}" stroke="#334155" stroke-dasharray="4,4" stroke-width="1.5" />'
            )

    # Footer
    svg_elements.extend([
        f'  <line x1="32" y1="{height - 50}" x2="928" y2="{height - 50}" stroke="#1e293b" stroke-width="1" />',
        f'  <circle cx="42" cy="{height - 28}" r="4" fill="#22c55e" />',
        f'  <text x="54" y="{height - 24}" fill="#64748b" font-size="11">Mermaid v11 syntax generated • Ready to export SVG / PNG</text>',
        '</svg>',
    ])

    return "\n".join(svg_elements)


def render_png(diagram_id: str, svg_content: str, diagram_code: Optional[str] = None) -> bytes:
    """Render and cache PNG bytes for diagram export."""
    if diagram_id in DIAGRAM_CACHE and DIAGRAM_CACHE[diagram_id].get("png"):
        return DIAGRAM_CACHE[diagram_id]["png"]

    # Generate high-resolution dark mode image with Pillow
    width, height = 1200, 700
    img = Image.new("RGB", (width, height), color=(11, 17, 32))
    draw = ImageDraw.Draw(img)

    # Background gradient / decorative elements
    draw.rectangle([(20, 20), (width - 20, height - 20)], outline=(30, 41, 59), width=2)
    draw.line([(40, 90), (width - 40, 90)], fill=(30, 41, 59), width=1)
    draw.line([(40, height - 60), (width - 40, height - 60)], fill=(30, 41, 59), width=1)

    # Header text
    draw.text((40, 38), "CODE OS ARCHITECTURE DIAGRAM", fill=(248, 250, 252))
    draw.text((40, 64), "Generated locally via codebase AST parser", fill=(148, 163, 184))

    # Parse some nodes from diagram_code or svg
    sample_nodes = ["Client Layer", "API Controller", "Core Service", "Database Model", "Message Queue"]
    if diagram_code:
        found = re.findall(r'\["([^"]+)"\]', diagram_code)
        if found:
            sample_nodes = [f.replace("\\n", " - ")[:30] for f in found[:8]]

    # Render card boxes
    card_w, card_h = 240, 90
    x_offset, y_offset = 60, 140
    for i, name in enumerate(sample_nodes[:6]):
        col = i % 3
        row = i // 3
        x = x_offset + col * (card_w + 100)
        y = y_offset + row * (card_h + 80)
        # Box
        outline_color = (56, 189, 248) if i % 2 == 0 else (168, 85, 247)
        draw.rounded_rectangle([(x, y), (x + card_w, y + card_h)], radius=10, fill=(15, 23, 42), outline=outline_color, width=2)
        draw.text((x + 20, y + 20), f"Component #{i+1}", fill=outline_color)
        draw.text((x + 20, y + 50), name, fill=(241, 245, 249))

        # Arrow to next
        if col < 2 and i + 1 < len(sample_nodes[:6]):
            arrow_x1 = x + card_w
            arrow_y1 = y + card_h // 2
            arrow_x2 = arrow_x1 + 100
            arrow_y2 = arrow_y1
            draw.line([(arrow_x1, arrow_y1), (arrow_x2, arrow_y2)], fill=(100, 116, 139), width=2)

    # Footer
    draw.text((50, height - 42), "CODE OS • Exported Architecture Diagram • Mermaid v11", fill=(100, 116, 139))

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    png_bytes = buf.getvalue()

    if diagram_id in DIAGRAM_CACHE:
        DIAGRAM_CACHE[diagram_id]["png"] = png_bytes
    return png_bytes
