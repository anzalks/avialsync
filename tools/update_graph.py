"""Build AvialView's committed, offline structural development graph.

This utility intentionally imports only Graphify's local AST, graph, report, and
export modules.  It never invokes Graphify's semantic, ingest, transcription, or
network-backed features, so a refresh consumes no API tokens and works offline.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = REPOSITORY_ROOT / "graphify-out"


def _word_count(paths: list[Path]) -> int:
    """Count source words for the report without processing non-source files."""
    return sum(len(path.read_text(encoding="utf-8", errors="ignore").split()) for path in paths)


def _write_offline_html(graph_path: Path) -> None:
    """Write a no-dependency local inspector for the portable graph JSON."""
    graph_data = json.loads(graph_path.read_text(encoding="utf-8"))
    nodes = graph_data.get("nodes", [])
    edges = graph_data.get("links", graph_data.get("edges", []))
    payload = json.dumps({"nodes": nodes, "edges": edges}).replace("</", "<\\/")
    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>AvialView offline development graph</title>
<style>
body {{ font: 14px system-ui, sans-serif; margin: 2rem; max-width: 72rem; color: #202124; }}
input {{ width: min(100%, 36rem); padding: .55rem; font: inherit; }}
li {{ margin: .5rem 0; }} .meta {{ color: #5f6368; }} code {{ word-break: break-word; }}
</style></head><body>
<h1>AvialView offline development graph</h1>
<p class="meta">{len(nodes)} nodes · {len(edges)} edges · structural extraction only</p>
<label>Search symbols and files <input id="search" autocomplete="off"></label>
<ul id="results"></ul>
<script>
const graph = {payload};
const edgesFor = new Map();
for (const edge of graph.edges) {{
  for (const id of [edge.source, edge.target, edge.from, edge.to]) {{
    if (id) edgesFor.set(id, (edgesFor.get(id) || 0) + 1);
  }}
}}
const results = document.getElementById('results');
document.getElementById('search').addEventListener('input', (event) => {{
  const query = event.target.value.trim().toLowerCase();
  results.replaceChildren();
  if (!query) return;
  graph.nodes.filter((node) => `${{node.label || ''}} ${{node.source_file || ''}}`
    .toLowerCase().includes(query)).slice(0, 100).forEach((node) => {{
    const item = document.createElement('li');
    const label = document.createElement('code');
    label.textContent = String(node.label || node.id);
    const metadata = document.createElement('span');
    metadata.className = 'meta';
    metadata.textContent = ` ${{node.source_file || 'no source'}} · ` +
      `${{edgesFor.get(node.id) || 0}} relationships`;
    item.append(label, metadata);
    results.append(item);
  }});
}});
</script></body></html>"""
    (OUTPUT_DIR / "graph.html").write_text(page, encoding="utf-8")


def _remove_volatile_commit_id(graph_path: Path) -> None:
    """Remove Graphify's automatic Git stamp so repeated refreshes are identical."""
    from graphify.paths import write_json_atomic

    graph_data = json.loads(graph_path.read_text(encoding="utf-8"))
    graph_data.pop("built_at_commit", None)
    write_json_atomic(graph_path, graph_data, indent=2)


def _deterministic_communities(graph: object) -> dict[int, list[str]]:
    """Group connected components without a stochastic community partitioner."""
    import networkx as nx

    components = [sorted(component) for component in nx.connected_components(graph)]
    components.sort(key=lambda component: (-len(component), tuple(component)))
    return {index: component for index, component in enumerate(components)}


def main() -> int:
    """Regenerate the portable graph artifacts from local source structure."""
    try:
        from graphify.analyze import god_nodes, suggest_questions, surprising_connections
        from graphify.build import build_from_json
        from graphify.cluster import score_all
        from graphify.export import to_json
        from graphify.extract import collect_files, extract
        from graphify.report import generate
    except ImportError as error:
        print(
            "Graphify is unavailable. Install the versioned dev stack with "
            "`conda run -n avialview pip install -e .[dev]`.",
            file=sys.stderr,
        )
        print(error, file=sys.stderr)
        return 2

    paths = collect_files(REPOSITORY_ROOT, root=REPOSITORY_ROOT)
    paths = [path for path in paths if OUTPUT_DIR not in path.parents]
    extraction = extract(paths, cache_root=OUTPUT_DIR, root=REPOSITORY_ROOT, parallel=False)
    graph = build_from_json(extraction, root=REPOSITORY_ROOT)
    communities = _deterministic_communities(graph)
    cohesion_scores = score_all(graph, communities)
    labels = {community_id: f"Community {community_id}" for community_id in communities}
    OUTPUT_DIR.mkdir(exist_ok=True)

    graph_path = OUTPUT_DIR / "graph.json"
    if not to_json(
        graph,
        communities,
        str(graph_path),
        force=True,
        community_labels=labels,
    ):
        print("Graphify declined to write graph.json.", file=sys.stderr)
        return 1
    _remove_volatile_commit_id(graph_path)
    _write_offline_html(graph_path)

    report = generate(
        graph,
        communities,
        cohesion_scores,
        labels,
        god_nodes(graph),
        surprising_connections(graph, communities),
        {"total_files": len(paths), "total_words": _word_count(paths)},
        {"input": 0, "output": 0},
        ".",
        suggested_questions=suggest_questions(graph, communities, labels),
    )
    (OUTPUT_DIR / "GRAPH_REPORT.md").write_text(report + "\n", encoding="utf-8")
    print(
        f"Updated offline graph: {graph.number_of_nodes()} nodes, {graph.number_of_edges()} edges."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
