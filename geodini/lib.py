from collections.abc import Callable
from typing import Any

from geodini import agents as geodini_agents


@geodini_agents.hookimpl
def get_geocoders(
    geocoders,
) -> list[Callable[[str, int | None], list[dict[str, Any]]]]:
    """Get a list of geocoders"""
    return [geodini_agents.utils.geocoder.geocode]
