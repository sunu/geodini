from collections.abc import Callable
from typing import Any

import pluggy

hookspec = pluggy.HookspecMarker("geodini")


@hookspec
def get_geocoders(
    geocoders: list[Callable[[str, int | None], list[dict[str, Any]]]],
) -> list[Callable[[str, int | None], list[dict[str, Any]]]]:
    """Get a list of geocoders"""
    pass
