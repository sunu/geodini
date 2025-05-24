from geodini import agents as geodini_agents
from typing import Optional


@geodini_agents.hookimpl
def get_geocoders(geocoders):
    """Here the caller expects us to return a list."""
    return [kba_geocoder]


def kba_geocoder(query: str, limit: Optional[int] = None):
    """Here the caller expects us to return a list."""
    data = [
        {
            "id": "kba-great-barrier-reef",
            "name": "Great Barrier Reef",
            "name_type": "primary",
            "country": "Australia",
            "subtype": "reef",
            "geometry": {
                "type": "Polygon",
                "coordinates": [
                    [
                        [142.0, -10.0],
                        [154.0, -10.0],
                        [154.0, -25.0],
                        [142.0, -25.0],
                        [142.0, -10.0],
                    ]
                ],
            },
            "hierarchies": [[]],
            "source_type": "kba",
        },
        {
            "id": "kba-amazon-rainforest",
            "name": "Amazon Rainforest",
            "name_type": "primary",
            "country": "Brazil",
            "subtype": "rainforest",
            "geometry": {
                "type": "Polygon",
                "coordinates": [
                    [
                        [-75.0, 5.0],
                        [-55.0, 5.0],
                        [-55.0, -15.0],
                        [-75.0, -15.0],
                        [-75.0, 5.0],
                    ]
                ],
            },
            "hierarchies": [[]],
            "source_type": "kba",
        },
    ]
    if "reef" in query.lower():
        return data[:1]
    elif "amazon" in query.lower():
        return data[1:]
    else:
        return []
