"""
Publisher tier definitions for filtering ComicVine search results.

Tier 1 — US: Major American publishers (highest priority).
Tier 2 — UK/EU: British and European publishers (second priority).
Other: Everything else (manga, Indian, etc.) — filtered out by default.
"""

# fmt: off
_US: frozenset[str] = frozenset({
    "marvel", "dc comics", "image comics", "dark horse comics",
    "idw publishing", "boom! studios", "boom studios",
    "dynamite entertainment", "dynamite",
    "valiant entertainment", "valiant",
    "archie comics", "archie comic publications",
    "aftershock comics", "oni press", "fantagraphics books",
    "drawn & quarterly", "top shelf productions",
    "vertigo", "wildstorm", "abc comics", "avatar press",
    "action lab entertainment", "zenescope entertainment",
    "black mask studios", "vault comics", "scout comics",
    "heavy metal", "antarctic press", "slave labor graphics",
    "kitchen sink press", "crossgen comics",
    "harris comics", "chaos! comics", "event comics",
    "america's best comics", "red circle comics",
    "dark horse", "idw", "oni", "boom",
})

_UK_EU: frozenset[str] = frozenset({
    "2000 ad", "rebellion", "rebellion publishing",
    "titan comics", "fleetway", "fleetway publications",
    "ipc magazines", "panini comics", "panini",
    "egmont", "humanoids", "humanoids publishing",
    "dargaud", "les humanoïdes associés", "casterman",
    "le lombard", "lombard", "marvel uk",
    "self made hero", "nobrow", "knockabout comics",
    "comixology originals",  # treated as neutral/US-adjacent
})
# fmt: on


def get_publisher_tier(publisher_name: str) -> str:
    """Return 'us', 'uk_eu', or 'other' for a publisher name."""
    if not publisher_name:
        return "other"
    normalized = publisher_name.lower().strip()
    if normalized in _US:
        return "us"
    if normalized in _UK_EU:
        return "uk_eu"
    return "other"


def filter_volumes_by_tier(
    volumes: list,
    tiers: tuple[str, ...] = ("us", "uk_eu"),
) -> list:
    """Filter a list of ComicVine volume dicts to the allowed publisher tiers."""
    result = []
    for vol in volumes:
        publisher_name = (vol.get("publisher") or {}).get("name", "")
        if get_publisher_tier(publisher_name) in tiers:
            result.append(vol)
    return result
