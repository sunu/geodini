from geodini import agents as geodini_agents
from typing import List, Callable, Optional, Dict, Any


@geodini_agents.hookimpl
def get_geocoders(
    geocoders,
) -> List[Callable[[str, Optional[int]], List[Dict[str, Any]]]]:
    """Get a list of geocoders"""
    return [geodini_agents.utils.geocoder.geocode]
