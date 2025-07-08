import os
import json
import hashlib
import logging
import asyncio
from typing import Any, Optional, Callable
from functools import wraps

import redis
from redis.exceptions import RedisError

logger = logging.getLogger(__name__)


class RedisCache:
    """Redis-based caching for function results"""

    def __init__(self):
        self.redis_client = None
        self._connect()

    def _connect(self):
        """Initialize Redis connection"""
        try:
            host = os.getenv("REDIS_HOST", "redis")
            port = int(os.getenv("REDIS_PORT", "6379"))
            password = os.getenv("REDIS_PASSWORD")
            db = int(os.getenv("REDIS_DB", "0"))

            self.redis_client = redis.Redis(
                host=host,
                port=port,
                password=password,
                db=db,
                decode_responses=True,
                socket_timeout=5,
                socket_connect_timeout=5,
                retry_on_timeout=True,
            )

            # Test connection
            self.redis_client.ping()
            logger.info(f"Connected to Redis at {host}:{port}")

        except (RedisError, Exception) as e:
            logger.warning(f"Redis connection failed: {e}. Caching disabled.")
            self.redis_client = None

    def _generate_cache_key(self, prefix: str, *args, **kwargs) -> str:
        """Generate a consistent cache key from function arguments"""
        # Create a deterministic representation of all arguments
        key_data = {
            "args": [str(arg) for arg in args],
            "kwargs": {k: str(v) for k, v in sorted(kwargs.items())},
        }
        key_string = json.dumps(key_data, sort_keys=True)
        logger.info(f"Key string: {key_string}")
        key_hash = hashlib.md5(key_string.encode()).hexdigest()
        return f"{prefix}:{key_hash}"

    def get(self, key: str) -> Optional[Any]:
        """Get cached data"""
        if not self.redis_client:
            return None

        try:
            cached_data = self.redis_client.get(key)
            if cached_data:
                return json.loads(cached_data)
        except (RedisError, json.JSONDecodeError) as e:
            logger.warning(f"Cache get error for key {key}: {e}")

        return None

    def set(self, key: str, data: Any, ttl: int = 3600) -> bool:
        """Set cached data with TTL (default 1 hour)"""
        if not self.redis_client:
            return False

        try:
            serialized_data = json.dumps(data, default=str)
            self.redis_client.setex(key, ttl, serialized_data)
            return True
        except (RedisError, TypeError) as e:
            logger.warning(f"Cache set error for key {key}: {e}")
            return False

    def delete(self, key: str) -> bool:
        """Delete cached data"""
        if not self.redis_client:
            return False

        try:
            return bool(self.redis_client.delete(key))
        except RedisError as e:
            logger.warning(f"Cache delete error for key {key}: {e}")
            return False

    def delete_all(self) -> bool:
        """Delete all cached data"""
        if not self.redis_client:
            return False

        try:
            return bool(self.redis_client.flushdb())
        except RedisError as e:
            logger.warning(f"Cache delete all error: {e}")
            return False

    def is_available(self) -> bool:
        """Check if Redis is available"""
        return self.redis_client is not None


# Global cache instance
cache = RedisCache()


def cached(
    prefix: str = "default",
    ttl: int = 3600,
    cache_condition: Optional[Callable] = None,
    key_func: Optional[Callable] = None,
):
    """
    Generalized cache decorator for both sync and async functions.

    Args:
        prefix: Cache key prefix (default: "default")
        ttl: Time-to-live in seconds (default: 3600 = 1 hour)
        cache_condition: Function that determines if result should be cached
        key_func: Custom function to generate cache key from args/kwargs

    Examples:
        @cached(prefix="geocode", ttl=3600)
        def geocode_func(query: str):
            ...

        @cached(prefix="search", ttl=1800, cache_condition=lambda result: result is not None)
        async def search_func(query: str):
            ...
    """

    def decorator(func: Callable) -> Callable:
        # Check if function is async
        is_async = asyncio.iscoroutinefunction(func)

        if is_async:

            @wraps(func)
            async def async_wrapper(*args, **kwargs):
                # Check if caching is disabled
                if os.getenv("DISABLE_CACHE", "false").lower() == "true":
                    logger.info(f"Cache disabled for {func.__name__}")
                    return await func(*args, **kwargs)

                # Generate cache key
                if key_func:
                    cache_key = key_func(*args, **kwargs)
                else:
                    cache_key = cache._generate_cache_key(prefix, *args, **kwargs)

                # Try to get from cache
                logger.info(f"Trying to get from cache for key async: {cache_key}")
                cached_result = cache.get(cache_key)
                if cached_result is not None:
                    logger.info(
                        f"Cache hit for {func.__name__} with key prefix: {prefix}"
                    )
                    return cached_result

                # Execute function
                logger.info(f"Cache miss for {func.__name__} with key prefix: {prefix}")
                result = await func(*args, **kwargs)

                # Check if we should cache this result
                should_cache = True
                if cache_condition:
                    should_cache = cache_condition(result)
                elif result is None or (
                    hasattr(result, "__len__") and len(result) == 0
                ):
                    should_cache = False

                # Cache the result if conditions are met
                if should_cache:
                    cache.set(cache_key, result, ttl)

                return result

            return async_wrapper

        else:

            @wraps(func)
            def sync_wrapper(*args, **kwargs):
                # Check if caching is disabled
                if os.getenv("DISABLE_CACHE", "false").lower() == "true":
                    logger.info(f"Cache disabled for {func.__name__}")
                    return func(*args, **kwargs)

                # Generate cache key
                if key_func:
                    cache_key = key_func(*args, **kwargs)
                else:
                    cache_key = cache._generate_cache_key(prefix, *args, **kwargs)

                # Try to get from cache
                logger.info(f"Trying to get from cache for key sync: {cache_key}")
                cached_result = cache.get(cache_key)
                if cached_result is not None:
                    logger.info(
                        f"Cache hit for {func.__name__} with key prefix: {prefix}"
                    )
                    return cached_result

                # Execute function
                logger.info(f"Cache miss for {func.__name__} with key prefix: {prefix}")
                result = func(*args, **kwargs)

                # Check if we should cache this result
                should_cache = True
                if cache_condition:
                    should_cache = cache_condition(result)
                elif result is None or (
                    hasattr(result, "__len__") and len(result) == 0
                ):
                    should_cache = False

                # Cache the result if conditions are met
                if should_cache:
                    cache.set(cache_key, result, ttl)

                return result

            return sync_wrapper

    return decorator


# Convenience functions for common cache patterns
def cache_invalidate(prefix: str, *args, **kwargs) -> bool:
    """Invalidate cache for specific function call"""
    cache_key = cache._generate_cache_key(prefix, *args, **kwargs)
    return cache.delete(cache_key)


def cache_invalidate_all() -> bool:
    """Invalidate all cache"""
    return cache.delete_all()


def cache_status() -> dict:
    """Get cache status information"""
    return {
        "available": cache.is_available(),
        "redis_client": cache.redis_client is not None,
        "disabled": os.getenv("DISABLE_CACHE", "false").lower() == "true",
    }


def init_cache():
    """Initialize cache based on environment settings"""
    if os.getenv("DISABLE_CACHE", "false").lower() == "true":
        logger.info("Cache disabled via DISABLE_CACHE environment variable")
        # Clear all cache on startup when cache is disabled
        if cache.is_available():
            cache.delete_all()
            logger.info("Cache cleared on startup")
    else:
        logger.info("Cache enabled")
