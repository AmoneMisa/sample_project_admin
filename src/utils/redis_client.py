import redis.asyncio

_redis = None

import os

def get_redis():
    global _redis
    if _redis is None:
        host = os.getenv("REDIS_HOST", "redis")
        port = os.getenv("REDIS_PORT", "6379")
        _redis = redis.asyncio.Redis.from_url(f"redis://{host}:{port}")
    return _redis
