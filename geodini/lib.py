from collections.abc import Callable
from typing import Any

from geodini.agents.utils.geocoder import geocode as overture_divisions_geocode
from geodini import agents as geodini_agents


@geodini_agents.hookimpl
def get_geocoders(
    geocoders,
) -> list[Callable[[str, int | None], list[dict[str, Any]]]]:
    """Get a list of geocoders"""
    return [overture_divisions_geocode]
