"""Pinned dataset sources: Amazon Reviews 2023 (McAuley Lab), SPEC §5.1 / ADR-0002.

The 5-core benchmark rating files and item metadata of the P1 candidate categories are
pinned (used for category profiling). The chosen category is **Video_Games** (ADR-0002);
its raw review file is pinned too, and :data:`VIDEO_GAMES` describes the dataset that
``make data`` builds.
"""

from __future__ import annotations

from dataclasses import dataclass

from commerce_agent.data.download import Source

BASE_URL = "https://mcauleylab.ucsd.edu/public_datasets/data/amazon_2023"

CANDIDATE_CATEGORIES: tuple[str, ...] = (
    "Video_Games",
    "Musical_Instruments",
    "Industrial_and_Scientific",
)

_FIVE_CORE_SHA256: dict[str, tuple[str, int]] = {
    "Video_Games": ("a2bde5f3b945960d161538c200dd87845e6ee471b46da96410dde61613c6901c", 12801967),
    "Musical_Instruments": (
        "e1cabe91651102ada04aee6836e6a890cd557386389da6ee9c3c80e8aa507260",
        8437657,
    ),
    "Industrial_and_Scientific": (
        "37dc32e707c6a89d2f8c4cf259fdec4e0ac1e2c7bd99c5886ee2c74c0ca99060",
        7114449,
    ),
}


def five_core_ratings(category: str) -> Source:
    """5-core rating-only benchmark file (user_id, parent_asin, rating, timestamp)."""
    sha, size = _FIVE_CORE_SHA256[category]
    return Source(
        name=f"5core-{category}",
        url=f"{BASE_URL}/benchmark/5core/rating_only/{category}.csv.gz",
        sha256=sha,
        size_bytes=size,
    )


_META_SHA256: dict[str, tuple[str, int]] = {
    "Video_Games": ("ced9696b0874121327a438bfe9d3d01aba45da158e58f94f4920352d75fc1fc9", 103096082),
    "Musical_Instruments": (
        "26a08fb09c39f9afc0982e7c101967df23a08ccdb0832657a3fe1af89e67c29d",
        155378934,
    ),
    "Industrial_and_Scientific": (
        "0beb251cec166347a3ec3ef23e55ec89f7fb27a6e8e9a0737d6b34cdc184ebcb",
        281523932,
    ),
}


def item_metadata(category: str) -> Source:
    """Raw item metadata (title, description, features, price, categories, ...)."""
    sha, size = _META_SHA256[category]
    return Source(
        name=f"meta-{category}",
        url=f"{BASE_URL}/raw/meta_categories/meta_{category}.jsonl.gz",
        sha256=sha,
        size_bytes=size,
    )


_REVIEWS_SHA256: dict[str, tuple[str, int]] = {
    "Video_Games": ("52d8762c94a5b99d3bccdb31c15cc6c99e05c89f9042cd3753b3b623a44bc193", 814206092),
}


def reviews(category: str) -> Source:
    """Raw reviews (rating, title, text, timestamp, helpful_vote, verified_purchase)."""
    sha, size = _REVIEWS_SHA256[category]
    return Source(
        name=f"reviews-{category}",
        url=f"{BASE_URL}/raw/review_categories/{category}.jsonl.gz",
        sha256=sha,
        size_bytes=size,
    )


@dataclass(frozen=True, slots=True)
class DatasetSpec:
    """What ``make data`` builds, and the row counts it must produce (FR-D1)."""

    category: str
    source: str
    k_core: int
    expected_users: int
    expected_items: int
    expected_interactions: int

    @property
    def ratings(self) -> Source:
        return five_core_ratings(self.category)

    @property
    def metadata(self) -> Source:
        return item_metadata(self.category)

    @property
    def reviews(self) -> Source:
        return reviews(self.category)


# Owner decision (P1): the official 5-core file is used as is (k = 5, no extra filtering).
VIDEO_GAMES = DatasetSpec(
    category="Video_Games",
    source="amazon2023/Video_Games",
    k_core=5,
    expected_users=94_762,
    expected_items=25_612,
    expected_interactions=814_586,
)
