# AvialView development graph

This directory is committed so the architecture graph is available on every development machine.

- `graph.html` is a self-contained browser inspector with no network dependency.
- `graph.json` is the portable graph data used by local graph queries.
- `GRAPH_REPORT.md` summarizes the current structural map.

The committed graph is an offline structural extraction of the source tree: it covers code symbols
and their relationships without any API-backed semantic extraction. Local interpreter selection,
absolute scan paths, caches, and temporary extraction files are intentionally ignored.

Run `conda run -n avialview python tools/update_graph.py` to refresh it locally. New clones can
enable the versioned post-commit hook with `conda run -n avialview python tools/install_git_hooks.py`.
The hook refreshes the working tree after relevant commits but never stages or commits automatically;
review and commit graph changes manually when wanted. No graph-generation step may enable semantic
extraction, transcription, web ingestion, or any API-backed feature.
