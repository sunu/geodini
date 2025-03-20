import pluggy

from typing import List, Callable, Optional, Dict, Any

hookspec = pluggy.HookspecMarker("geodini")


@hookspec
def get_geocoders(
    geocoders: List[Callable[[str, Optional[int]], List[Dict[str, Any]]]],
) -> List[Callable[[str, Optional[int]], List[Dict[str, Any]]]]:
    """Get a list of geocoders"""
    pass
