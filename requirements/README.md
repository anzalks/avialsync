# Tested dependency sets

`ci-py3.11.txt` and `ci-py3.12.txt` constrain the complete runtime, test,
documentation and bundler dependency closure for the supported Python versions.
Platform-only dependencies are pinned here but installed only when their own
package metadata requires them. These are constraints, not installation lists.
Ordinary `pip install avialsync` retains the ranges in `pyproject.toml`.
No direct dependency or operating-system requirement is added.

CI and release jobs set both `PIP_CONSTRAINT` and `PIP_BUILD_CONSTRAINT` to an
absolute checkout path, bootstrap the constrained pip, and include these files
in pip cache keys. Build constraints also pin hatchling in isolated builds;
regular constraints alone no longer affect those builds in pip 26.2.
[pip documents the separate build constraints](https://pip.pypa.io/en/stable/user_guide/#build-constraints).
Read the Docs uses the same Python 3.12 set in its install job.

Reproduce a development install with:

```shell
conda run -n avialsync python -m pip install --upgrade pip -c requirements/ci-py3.12.txt
conda run -n avialsync python -m pip install -c requirements/ci-py3.12.txt --build-constraint requirements/ci-py3.12.txt -e ".[dev,docs]" pyinstaller
conda run -n avialsync python -m pip check
```

Use the 3.11 file with the verified `avialsync311` environment for the lower
bound. Never freeze an entire personal environment: it can include unrelated
tools or an old editable checkout. Record only the dependency closure of this
project's runtime/dev/docs extras plus the build and bundling tools.

For an update, change pins deliberately, retain PySide6's declared upper bound,
and resolve binary wheels for Linux x86_64, macOS arm64 and Windows x86_64 on
both interpreters. Include platform-only dependencies when resolving off-host:
pip's platform flags choose wheels but do not replace every environment marker.
Ubuntu 24.04 supports the Qt wheel's manylinux_2_34 tag; a resolver restricted
to manylinux_2_28 falsely rejects it. Check every resolved dependency against a
pin, then run correctness, strict typing, docs, packaging smoke and local
performance checks before pushing. Resolution is preflight evidence; the six
native CI jobs remain the execution gate.

The initial sets were resolved on 2026-10-14, with no unpinned dependencies in
any of the six reports. They preserve the locally tested NumPy, PyAV, Polars,
Qt, mypy and tooling versions for each interpreter.
