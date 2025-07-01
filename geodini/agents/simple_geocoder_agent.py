import time
from dataclasses import dataclass
from pprint import pprint
from concurrent.futures import ThreadPoolExecutor

import pluggy
from pydantic_ai import Agent

from geodini import hookspecs, lib
from geodini.cache import cached


def get_plugin_manager():
    pm = pluggy.PluginManager("geodini")
    pm.add_hookspecs(hookspecs)
    pm.load_setuptools_entrypoints("geodini")
    pm.register(lib)
    return pm


@dataclass
class Place:
    id: str
    hierarchy: list[str]
    name: str
    country: str
    subtype: str


@dataclass
class RerankingContext:
    query: str
    results: list[Place]


@dataclass
class RerankingResult:
    most_probable: str
    next_probable: list[str]


rerank_agent = Agent(
    # 4o-mini is smarter than 3.5-turbo. And does better in edge cases.
    "openai:gpt-4.1-mini",
    output_type=RerankingResult,
    deps_type=RerankingContext,
    system_prompt="""
        Given the search query and results, rank them in order of 
        relevance to the query.
        Results can be administrative regions, cities, countries, lakes, mountains, forests
        or any other geographical entity. This is described by the subtype field.
        The hierarchy field describes the administrative hierarchy of the place if known.
        Consider name, hierarchy, subtype, and country to determine the relevance to the query.
        
        From the results list, return a JSON object with:
        1. "most_probable": The ID of the most relevant result
        2. "next_probable": A list of IDs of the next 5 most relevant results in order of relevance

        Make sure the returned IDs are in the results list.

        While reranking, consider the following:
        - The query might be a shortened name and the result might be a full name. For example, "United States" or "United States of America" is a match for "USA" or "The US".
        - The query might be a informal name and the result might be a formal name. For example, "District of Columbia" is a candidate for "DC" or "Washington, D.C." or even just "Washington". So consider all possible variations of the query when matching.
        - Consider geographical context. For example, "London in Canada" should rank "London, Ontario" higher than "London, England" because it is more likely to be the correct answer.   
""",
)


@dataclass
class SearchContext:
    query: str


@dataclass
class RephrasedQuery:
    query: str
    country_code: str | None
    exact: bool


rephrase_agent = Agent(
    "openai:gpt-4.1-mini",
    output_type=RephrasedQuery,
    deps_type=SearchContext,
    system_prompt="""
        Given the search query, rephrase it to be more specific and accurate. We will be using this query to search for places in the overture database. So it helps to make the query be full formal name of the place.
        
        Extract:
        1. The main search term (place name) - for example, "the city of San Francisco" should return "San Francisco", "New York City" should return "New York", "Paris, TX" should return "Paris",
            "Sahara Desert" should return "Sahara", "The Himalayan mountain range" should return "Himalaya", "The Amazon rainforest" should return "Amazon".
            If the query is a shortened name, return the full name - for example, "usa" or "The US" should return "United States" and so on.
            If the query is a informal name, return the formal name along with the informal name - for example, "Washington DC" should return "Washington, District of Columbia".
        2. Country code (ISO 2-letter code) if a specific country is mentioned
        3. Whether an exact match is requested (e.g., "exactly", "precisely")
        
        Only return the JSON object, nothing else.
    """,
)


@cached(
    prefix="agent_search",
    ttl=1800,  # 30 minutes
    cache_condition=lambda result: result
    and result.get("results")
    and len(result["results"]) > 0,  # Only cache if there are results
)
async def search_places(query: str) -> dict:
    print(f"Starting search for {query}")
    pm = get_plugin_manager()
    geocoders = pm.hook.get_geocoders(geocoders=list())
    print(f"Geocoders: {geocoders}")
    start_time = time.time()
    rephrased_query = await rephrase_agent.run(
        user_prompt=f"Search query: {query}",
        deps=SearchContext(query=query),
    )
    pprint(rephrased_query.output)
    rephrased_query_time = time.time() - start_time
    print(f"Rephrased query time: {rephrased_query_time} seconds")

    geocoding_start_time = time.time()
    results = []
    for geocoder_group in geocoders:
        # Execute in ThreadPoolExecutor to avoid blocking the main thread
        with ThreadPoolExecutor() as executor:
            futures = [
                executor.submit(geocoder, rephrased_query.output.query)
                for geocoder in geocoder_group
            ]
            for future in futures:
                results.extend(future.result())
    geocoding_time = time.time() - geocoding_start_time
    print(f"Geocoding time: {geocoding_time} seconds")

    reranking_start_time = time.time()
    for result in results:
        hierarchy = []
        if result["hierarchies"] is not None:
            result["hierarchy"] = result["hierarchies"][0]
        else:
            result["hierarchy"] = []
        for level in result["hierarchy"]:
            hierarchy.append(level["name"])
        result["hierarchy"] = hierarchy
    places = []
    for result in results:
        places.append(
            Place(
                id=result["id"],
                hierarchy=result["hierarchy"],
                name=result["name"],
                country=result["country"],
                subtype=result["subtype"],
            )
        )

    if places:
        user_prompt = f"""
        Rerank the following results based on the search query:
        search query: {query},
        results: {places}
        """
        pprint(user_prompt)
        reranked_results = await rerank_agent.run(
            user_prompt=user_prompt,
            deps=RerankingContext(query=query, results=places),
        )
        reranking_time = time.time() - reranking_start_time
        print(f"Reranking time: {reranking_time} seconds")

    total_time = time.time() - start_time
    print(f"Total time: {total_time} seconds")

    # pprint(results)

    # Create a dictionary for quick lookup by ID
    results_dict = {
        result["id"]: {
            "id": result["id"],
            "name": result["name"],
            "country": result["country"],
            "subtype": result["subtype"],
            "source_type": result["source_type"],
            "geometry": result["geometry"],
            "hierarchy": result["hierarchy"],
        }
        for result in results
    }

    if places:
        most_probable = results_dict.get(reranked_results.output.most_probable)
        next_probable = [
            results_dict.get(place_id)
            for place_id in reranked_results.output.next_probable
        ]
    else:
        most_probable = None
        next_probable = []

    return {
        "most_probable": most_probable,
        "next_probable": next_probable,
        "results": [most_probable, *next_probable],
        "query": query,
        "rephrased_query": rephrased_query.output.query,
        "country_code": rephrased_query.output.country_code,
        "exact": rephrased_query.output.exact,
        "time_taken": total_time,
    }


async def main():
    results = await search_places("the other London")
    # results = await search_places("georgia the country")
    # results = await search_places("amazon rainforest")
    print(results["time_taken"])
    print(results["most_probable"])
    print(results["next_probable"])
    print(results[0])


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
