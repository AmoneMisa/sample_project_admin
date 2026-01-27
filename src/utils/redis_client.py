import redis.asyncio

_redis = None

def get_redis():
    global _redis
    if _redis is None:
        _redis = redis.asyncio.Redis.from_url("redis://localhost:6379")
    return _redis
