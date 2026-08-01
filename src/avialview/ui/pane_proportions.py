"""Hold each pane's share of the workspace steady while the window is resized.

``QSplitter`` does not preserve ratios. It distributes the *delta* of a resize
by stretch factor, and a pane already sitting on its minimum size absorbs none
of that delta — its sibling takes the whole change. Two consequences were
measurable in this window:

* Shrinking 1280x800 to 1000x600 moved the video/plot split from 34:66 to
  47:53, because the video area was pinned at a minimum and the plot area paid
  the entire loss. Growing the window again did not restore the ratio: the
  drift is one-way and accumulates over a session.
* The video/3D split moved from 59:41 to 47:53 across the same resize, for the
  same reason.

This module reallocates the whole span by remembered fractions instead, so the
ratio the user arranged is the ratio they keep at every window size the
minimums physically allow. Nothing here changes a control's size, font, or
text — only how many pixels each pane is handed.
"""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import QObject, Qt
from PySide6.QtWidgets import QSplitter


def distribute(fractions: Sequence[float], span: int, minimums: Sequence[int]) -> list[int]:
    """Split *span* pixels across panes by *fractions*, never below *minimums*.

    A pane whose proportional share would fall under its minimum is pinned
    there and removed from the pool; the rest re-share what is left. Pinning
    one pane can push another under its own minimum, so this repeats until the
    set of pinned panes stops growing — at most one pass per pane.

    The returned sizes always sum to exactly *span*, because ``QSplitter``
    silently reinterprets a vector that does not, which is the same class of
    "somebody else decides" that this module exists to remove. The one
    exception is a *span* smaller than the minimums can satisfy: the minimums
    are returned as-is and Qt clamps, since no allocation can honour both.
    """
    count = len(fractions)
    if count == 0:
        return []
    if len(minimums) != count:
        raise ValueError("fractions and minimums must describe the same panes")

    span = max(0, span)
    floors = [max(0, minimum) for minimum in minimums]
    if sum(floors) >= span:
        return floors

    weights = [max(0.0, fraction) for fraction in fractions]
    if sum(weights) <= 0.0:
        weights = [1.0] * count

    pinned = [False] * count
    while True:
        free_span = span - sum(floors[i] for i in range(count) if pinned[i])
        free_weight = sum(weights[i] for i in range(count) if not pinned[i])
        if free_weight <= 0.0:
            break
        newly_pinned = False
        for i in range(count):
            if not pinned[i] and free_span * weights[i] / free_weight < floors[i]:
                pinned[i] = True
                newly_pinned = True
        if not newly_pinned:
            break

    free_span = span - sum(floors[i] for i in range(count) if pinned[i])
    free_weight = sum(weights[i] for i in range(count) if not pinned[i])
    sizes = [0] * count
    remainders: list[tuple[float, int]] = []
    for i in range(count):
        if pinned[i] or free_weight <= 0.0:
            sizes[i] = floors[i]
            continue
        exact = free_span * weights[i] / free_weight
        sizes[i] = int(exact)
        remainders.append((exact - sizes[i], i))

    # Hand the pixels lost to truncation to the panes that lost the most of one.
    for _, index in sorted(remainders, reverse=True)[: max(0, span - sum(sizes))]:
        sizes[index] += 1
    shortfall = span - sum(sizes)
    if shortfall:
        sizes[sizes.index(max(sizes))] += shortfall
    return sizes


class PaneProportions(QObject):
    """Remember every managed splitter's pane ratio and restore it on resize.

    The remembered ratio is always one the layout actually produced, never one
    computed from requested sizes: :meth:`record` is what seeds it, and it runs
    against real geometry. A splitter with nothing recorded yet is recorded
    rather than rearranged, so adopting this class cannot move a pane the user
    has not moved themselves.
    """

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._fractions: dict[QSplitter, tuple[float, ...]] = {}
        self._splitters: list[QSplitter] = []

    def track(self, *splitters: QSplitter) -> None:
        """Manage *splitters*, adopting each one's ratio the first time it lays out."""
        for splitter in splitters:
            if splitter in self._splitters:
                continue
            self._splitters.append(splitter)
            # A drag is the user overriding the remembered ratio, so it becomes
            # the remembered ratio. Without this, the next window resize would
            # undo every handle they moved.
            splitter.splitterMoved.connect(
                lambda _pos, _index, target=splitter: self.record(target)
            )

    def record(self, splitter: QSplitter) -> None:
        """Adopt *splitter*'s current pane ratio as the one to hold.

        A visible pane measuring zero means the splitter has not laid out yet
        (or is mid-rearrangement), and the ratio on offer is not one the user
        will ever see. Recording it would pin that pane at its minimum forever,
        so this waits for a real arrangement instead.
        """
        sizes = splitter.sizes()
        total = sum(sizes)
        if total <= 0:
            return
        for index, size in enumerate(sizes):
            widget = splitter.widget(index)
            if size <= 0 and widget is not None and not widget.isHidden():
                return
        self._fractions[splitter] = tuple(size / total for size in sizes)

    def set_fractions(self, splitter: QSplitter, weights: Sequence[float]) -> None:
        """Pin an explicit ratio for *splitter*, given as any positive weights.

        Used for the first-run defaults, which are written as pixel counts:
        those describe a ratio, not a size, and only the ratio outlives the
        first window resize.
        """
        total = sum(max(0.0, weight) for weight in weights)
        if total <= 0.0:
            raise ValueError("splitter default weights must include something positive")
        self._fractions[splitter] = tuple(max(0.0, weight) / total for weight in weights)

    def record_all(self) -> None:
        """Adopt the current ratio of every managed splitter.

        Call after anything that legitimately rearranges panes — restoring a
        saved layout, showing or hiding a pane — so the new arrangement is what
        gets held rather than being undone by the next resize.
        """
        for splitter in self._splitters:
            self.record(splitter)

    def reapply(self) -> None:
        """Give every managed splitter its remembered ratio at the current size."""
        for splitter in self._splitters:
            fractions = self._fractions.get(splitter)
            sizes = splitter.sizes()
            if fractions is None or len(fractions) != len(sizes):
                # Either the first layout, or panes were added or removed since
                # the ratio was recorded. Adopt what is on screen instead of
                # forcing a stale vector onto a different set of panes.
                self.record(splitter)
                continue
            span = sum(sizes)
            if span <= 0:
                continue
            target = distribute(fractions, span, _pane_minimums(splitter))
            if target != sizes:
                splitter.setSizes(target)


def _pane_minimums(splitter: QSplitter) -> list[int]:
    """Return the smallest each pane may be, along the splitter's orientation.

    A hidden pane reports 0: it holds no space, and letting its minimum enter
    the allocation would reserve pixels for a pane nobody can see. This is the
    3D tracking pane's normal state, since it only appears once a source has
    XYZ triplets.
    """
    horizontal = splitter.orientation() == Qt.Orientation.Horizontal
    minimums: list[int] = []
    for index in range(splitter.count()):
        widget = splitter.widget(index)
        if widget is None or widget.isHidden():
            minimums.append(0)
            continue
        hint = widget.minimumSizeHint()
        explicit = widget.minimumWidth() if horizontal else widget.minimumHeight()
        hinted = hint.width() if horizontal else hint.height()
        minimums.append(max(0, explicit, hinted))
    return minimums
