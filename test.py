import redis
from redis import ConnectionPool
import time
import json

testing = True

atomic_flip_script = """
local frozen_bitset = KEYS[1]
local frozen_count_key = KEYS[2]
local index = tonumber(ARGV[1])

local was_already_frozen = redis.call('GETBIT', frozen_bitset, index)
if was_already_frozen == 0 then
    redis.call('SETBIT', frozen_bitset, index, 1)
    redis.call('INCR', frozen_count_key)
    return 1
else
    return 0
end
"""

def get_redis_client():
    pool = None
    if testing:
        pool = ConnectionPool(
                host="127.0.0.1",
                port=57811,
                #username=os.environ.get('REDIS_USERNAME', 'default'),
                #password=os.environ.get('REDIS_PASSWORD', ''),
                db=0,
                #connection_class=redis.SSLConnection,
                decode_responses=True,
                max_connections=1
                )
    else:
        raise Exception("FIXME")

    return redis.Redis(connection_pool=pool)


def get_time(r):
    seconds, microseconds = r.time()
    return seconds * 1000 + microseconds // 1000

def get_freeze_time(r):
    t = r.get("freeze_time_ms")
    return int(t)

def freeze_bits(r, atomic_flip_hash):
    current_time = get_time(r)
    freeze_time = get_freeze_time(r)
    safety_buffer = freeze_time * 0.1
    threshold = current_time - freeze_time - safety_buffer

    chunk_size = 1
    cursor = -1
    stats = {
        "total_checked": 0,
        "eligible_for_freezing": 0,
        "newly_frozen": 0,
        "already_frozen": 0
    }

    while cursor != 0:
        if cursor == -1: cursor = 0
        cursor, chunk = r.hscan("last_checked", cursor, count=chunk_size)

        for index, last_checked in chunk.items():
            index = int(index)
            last_checked = int(last_checked)
            stats["total_checked"] += 1

            if last_checked != 0 and last_checked < threshold:
                stats["eligible_for_freezing"] += 1

                did_freeze = r.evalsha(atomic_flip_hash, 2, "frozen_bitset", "frozen_count", index)

                if did_freeze == 1:
                    stats["newly_frozen"] += 1
                    r.publish("frozen_bit_channel", json.dumps([index]))
                else:
                    stats["already_frozen"] += 1

    return stats


if __name__ == "__main__":
    r = get_redis_client()
    atomic_flip_hash = r.script_load(atomic_flip_script)
    print(freeze_bits(r, atomic_flip_hash))
