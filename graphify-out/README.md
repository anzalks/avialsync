# AvialSync development graph

This directory is committed so the architecture graph is available on every development machine.

- `graph.html` is a self-contained browser inspector with no network dependency.
- `graph.json` is the portable graph data used by local graph queries.
- `GRAPH_REPORT.md` summarizes the current structural map.

This is a local developer convenience, not an AvialSync dependency or CI input. To enable the
versioned hook in a clone, run `git config core.hooksPath .githooks`. Each local commit runs the
already-installed `graphify` command and leaves any changed graph artifacts unstaged for manual review
and commit. It never runs in CI or changes the application environment.
