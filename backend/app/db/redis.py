from redis.asyncio import Redis, from_url

from app.core.config import settings

# from_url builds a client and connection pool lazily; it does not connect until
# a command is issued, so importing this module (e.g. under tests) is side-effect
# free. decode_responses=True so counters come back as str, not bytes.
redis_client: Redis = from_url(settings.redis_url, decode_responses=True)


async def get_redis() -> Redis:
    return redis_client
