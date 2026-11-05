import os
import logging
from typing import Optional, Tuple
import redis.asyncio as aioredis

logger = logging.getLogger("redis_concurrency")

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", None)

redis_client: Optional[aioredis.Redis] = None

# Lua script to release lock atomically only if the caller owns it
LUA_RELEASE_LOCK = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
else
    return 0
end
"""


async def get_redis_client() -> aioredis.Redis:
    global redis_client
    if redis_client is None:
        redis_client = aioredis.Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            password=REDIS_PASSWORD,
            decode_responses=True,
            socket_timeout=5.0,
            socket_connect_timeout=5.0,
            retry_on_timeout=True
        )
    return redis_client


async def close_redis_client():
    global redis_client
    if redis_client:
        await redis_client.close()
        redis_client = None


async def acquire_seat_lock(seat_id: int, student_id: str, ttl_seconds: int = 30) -> Tuple[bool, str]:
    """
    Acquire an atomic provisional lock for a seat using Redis SETNX.
    SET key value EX ttl NX
    Returns (True, message) if acquired, (False, reason) if conflict.
    """
    try:
        r = await get_redis_client()
        key = f"lock:seat:{seat_id}"
        
        # SET key value EX seconds NX: Only set the key if it does not already exist
        acquired = await r.set(key, student_id, ex=ttl_seconds, nx=True)
        
        if acquired:
            logger.info(f"[LOCK_ACQUIRED] Seat {seat_id} locked by {student_id} for {ttl_seconds}s")
            return True, f"Provisional lock granted for {ttl_seconds}s"
        
        # If lock exists, check who holds it
        current_holder = await r.get(key)
        if current_holder == student_id:
            # Re-entrant: extend TTL
            await r.expire(key, ttl_seconds)
            return True, f"Provisional lock extended for {ttl_seconds}s"
            
        logger.warning(f"[LOCK_CONFLICT] Seat {seat_id} requested by {student_id} but already held by {current_holder}")
        return False, f"Seat {seat_id} is currently being held by another student"

    except Exception as e:
        logger.error(f"Redis lock error: {str(e)}")
        # In case Redis is down or unreachable during demo, raise error
        raise e


async def release_seat_lock(seat_id: int, student_id: str) -> bool:
    """
    Atomically release a seat lock using a Lua script to ensure 
    a student only releases their own lock.
    """
    try:
        r = await get_redis_client()
        key = f"lock:seat:{seat_id}"
        result = await r.eval(LUA_RELEASE_LOCK, 1, key, student_id)
        return bool(result)
    except Exception as e:
        logger.error(f"Redis unlock error: {str(e)}")
        return False


async def get_seat_lock_info(seat_id: int) -> Tuple[bool, Optional[str], int]:
    """
    Check if a seat is locked, by whom, and remaining TTL.
    Returns (is_locked, locked_by, ttl_remaining_seconds)
    """
    try:
        r = await get_redis_client()
        key = f"lock:seat:{seat_id}"
        pipe = r.pipeline()
        pipe.get(key)
        pipe.ttl(key)
        holder, ttl = await pipe.execute()
        
        if holder is not None and ttl > 0:
            return True, holder, ttl
        return False, None, 0
    except Exception as e:
        logger.error(f"Error fetching lock info for seat {seat_id}: {str(e)}")
        return False, None, 0


async def clear_all_locks():
    """Clear all active seat locks for demonstration reset."""
    try:
        r = await get_redis_client()
        keys = await r.keys("lock:seat:*")
        if keys:
            await r.delete(*keys)
    except Exception as e:
        logger.error(f"Error clearing locks: {str(e)}")
