from __future__ import annotations

from collections.abc import Iterable

from estate_sale_finder.watchlists import WatchlistProfile


def matching_watchlists(
    category: str,
    profiles: Iterable[WatchlistProfile],
) -> list[WatchlistProfile]:
    return [profile for profile in profiles if category in profile.targets]


def category_matches_watchlist(category: str, profile: WatchlistProfile) -> bool:
    return category in profile.targets
