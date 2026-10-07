"""Which dimension of an image stack is time, channel or depth (D-194).

A stack opens with an axis order straight away -- the file's own tags when they
make sense, otherwise one inferred from the shape -- and the imaging pane offers
every other valid order by name and size for the user to switch to. Asking
first, as D-190 did, stopped people who could not say what "TCZYX" meant from
seeing their data at all.

The last two dimensions are always the image (Y, X); the leading ones are some
arrangement of time (T, required), channels (C) and depth (Z).
"""

from __future__ import annotations

from itertools import permutations

__all__ = ["axis_choices", "default_axes", "describe_axes", "valid_axes"]

#: Leading-axis letters other than time.
_EXTRA = "CZ"

#: Largest dimension read as channels by default; fluorescence stacks rarely
#: carry more than four, while depth and time usually exceed it.
_MAX_DEFAULT_CHANNELS = 4

_NAMES = {"T": "Time", "C": "Channels", "Z": "Depth"}


def valid_axes(shape: tuple[int, ...], axes: str) -> bool:
    """Whether *axes* names every dimension of *shape* once, ending in YX, with T."""
    return (
        len(axes) == len(shape)
        and len(set(axes)) == len(axes)
        and axes.endswith("YX")
        and "T" in axes
        and set(axes[:-2]) <= set("T" + _EXTRA)
    )


def axis_choices(shape: tuple[int, ...]) -> list[str]:
    """Every valid axis order for *shape*, time-first orders first."""
    leading = len(shape) - 2
    if leading < 1 or leading > 3:
        return []
    found: list[str] = []
    for extra in permutations(_EXTRA, leading - 1):
        for order in permutations(("T", *extra)):
            axes = "".join(order) + "YX"
            if axes not in found:
                found.append(axes)
    return sorted(found, key=lambda axes: (axes.index("T"), axes))


def default_axes(shape: tuple[int, ...], tagged: str = "") -> str:
    """The order a stack opens with: its tags if valid, else one inferred from sizes.

    Inference: the largest leading dimension is time, a leading dimension of at
    most four is channels, anything else is depth. Tags such as ImageJ's ``Z``
    for plain slices are common and wrong for movies, so they are read as
    letters only when they already form a valid order.
    """
    tagged = tagged.upper()
    if valid_axes(shape, tagged):
        return tagged
    leading = list(shape[:-2])
    if not leading:
        return ""
    letters = [""] * len(leading)
    letters[max(range(len(leading)), key=lambda index: leading[index])] = "T"
    for index in sorted(range(len(leading)), key=lambda index: leading[index]):
        if letters[index]:
            continue
        if "C" not in letters and leading[index] <= _MAX_DEFAULT_CHANNELS:
            letters[index] = "C"
        elif "Z" not in letters:
            letters[index] = "Z"
        else:
            letters[index] = "C"
    axes = "".join(letters) + "YX"
    return axes if valid_axes(shape, axes) else ""


def describe_axes(shape: tuple[int, ...], axes: str) -> str:
    """Name an order by what each leading dimension would be, with its size."""
    return " · ".join(
        f"{_NAMES[letter]} {size}" for letter, size in zip(axes[:-2], shape[:-2], strict=False)
    )
