"""Candidate filters (FR-R2): already interacted, unavailable, category constraints.

Filters produce boolean "allowed" masks; :func:`apply` sets disallowed scores to
``-inf`` so that no later stage (fusion, ranking, diversity) can resurrect them.
"""

from __future__ import annotations

from collections.abc import Collection

import numpy as np
import numpy.typing as npt

from commerce_agent.rec.data import Catalog, FloatArray, Histories, IntArray, seen_mask

BoolArray = npt.NDArray[np.bool_]


def not_already_interacted(hist: Histories, rows: IntArray, n_items: int) -> BoolArray:
    """``(B, n_items)``: False for items in the user's history (the purchase proxy)."""
    return ~seen_mask(hist, rows, n_items)


def available(catalog: Catalog, *, allow_unknown: bool = True) -> BoolArray:
    """``(n_items,)``: False where simulated stock is 0. Unknown stock (-1) is allowed by
    default, because recommendation is a read path and fails open (ADR-0008)."""
    stock = catalog.available
    return (stock > 0) | ((stock < 0) & allow_unknown)


def category_constraint(
    catalog: Catalog,
    *,
    include: Collection[str] | None = None,
    exclude: Collection[str] | None = None,
) -> BoolArray:
    """``(n_items,)``: an item matches a name if it appears anywhere in its category path.

    ``include``: keep only items matching at least one name. ``exclude``: drop items
    matching any name. Exclusion wins over inclusion.
    """
    inc = set(include or ())
    exc = set(exclude or ())
    allowed = np.ones(catalog.n_items, dtype=bool)
    if not inc and not exc:
        return allowed
    for i, path in enumerate(catalog.category_paths):
        names = set(path)
        if inc and not (names & inc):
            allowed[i] = False
        if exc and names & exc:
            allowed[i] = False
    return allowed


def apply(scores: FloatArray, allowed: BoolArray) -> FloatArray:
    """Return a copy of ``scores`` with disallowed entries set to ``-inf``.

    ``allowed`` may be ``(n_items,)`` (same for every row) or ``(B, n_items)``.
    """
    out = scores.copy()
    if allowed.ndim == 1:
        out[:, ~allowed] = -np.inf
    else:
        out[~allowed] = -np.inf
    return out
