from geodini import tools as geodini_tools
from typing import List, Callable, Optional, Dict, Any


@geodini_tools.hookimpl
def get_geocoders(
    geocoders,
) -> List[Callable[[str, Optional[int]], List[Dict[str, Any]]]]:
    """Get a list of geocoders"""
    return [geodini_tools.geocoder.geocode]
