# AvialView development graph

This directory is committed so the architecture graph is available on every development machine.

- `graph.html` is a self-contained browser view.
- `graph.json` is the portable graph data used by local graph queries.
- `GRAPH_REPORT.md` summarizes the current structural map.

The committed graph is an offline structural extraction of the source tree: it covers code symbols
and their relationships without any API-backed semantic extraction. Local interpreter selection,
absolute scan paths, caches, and temporary extraction files are intentionally ignored. Rebuild those
machine-local files with the graph tool after installing it in the target development environment.
