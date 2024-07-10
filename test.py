import redis
from redis import ConnectionPool
import time
import json
from collections import defaultdict

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
                port=61003,
                #username=os.environ.get('REDIS_USERNAME', 'default'),
                #password=os.environ.get('REDIS_PASSWORD', ''),
                db=0,
                #connection_class=redis.SSLConnection,
                #decode_responses=True,
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

def bytes_to_bits(byte_string):
    return ''.join(format(byte, '08b') for byte in byte_string)

def find_dense_regions(bitstring, bit_kind="0", region_size=10000, top_n=3):
    regions = defaultdict(int)
    for i, bit in enumerate(bitstring):
        if bit == bit_kind:  # Counting unfrozen/unchecked boxes
            regions[i // region_size] += 1
    return sorted(regions.items(), key=lambda x: x[1], reverse=True)[:top_n]

def format_dense_regions(region):
    return ", ".join([":".join(map(str, x)) for x in region])

def find_longest_streaks(bitstring):
    longest_0 = 0
    longest_1 = 0
    longest_0_idx = 0
    longest_1_idx = 0
    current_0 = 0
    current_1 = 0
    current_0_idx = 0
    current_1_idx = 0

    on_a_zero = True
    
    for idx, bit in enumerate(bitstring):
        if bit == '0':
            if not on_a_zero:
                on_a_zero = True
                current_0_idx = idx

            current_0 += 1
            current_1 = 0
            if current_0 > longest_0:
                longest_0 = current_0
                longest_0_idx = current_0_idx
        else:
            if on_a_zero:
                on_a_zero = False
                current_1_idx = idx
            current_1 += 1
            current_0 = 0
            if current_1 > longest_1:
                longest_1 = current_1
                longest_1_idx = current_1_idx
    return [[longest_0, longest_0_idx], [longest_1, longest_1_idx]]

def freeze_bits(r, atomic_flip_hash):
    current_time = get_time(r)
    freeze_time = get_freeze_time(r)
    safety_buffer = freeze_time * 0.1
    threshold = current_time - freeze_time - safety_buffer

    chunk_size = 5000
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
            index = int(index.decode("utf-8"))
            last_checked = int(last_checked.decode("utf-8"))
            stats["total_checked"] += 1

            if last_checked != 0 and last_checked < threshold:
                stats["eligible_for_freezing"] += 1

                did_freeze = r.evalsha(atomic_flip_hash, 2, "frozen_bitset", "frozen_count", index)

                if did_freeze == 1:
                    stats["newly_frozen"] += 1
                    r.publish("frozen_bit_channel", json.dumps([index]))
                else:
                    stats["already_frozen"] += 1

    stats["frozen_count"] = stats["newly_frozen"] + stats["already_frozen"]
    stats["freeze_time_ms"] = freeze_time
    return stats

if __name__ == "__main__":
    r = get_redis_client()
    atomic_flip_hash = r.script_load(atomic_flip_script)
    stats = freeze_bits(r, atomic_flip_hash)
    sunset_bitset = bytes_to_bits(r.get("sunset_bitset"))
    sunset_streaks = find_longest_streaks(sunset_bitset)

    frozen_bitset = bytes_to_bits(r.get("frozen_bitset"))
    frozen_streaks = find_longest_streaks(frozen_bitset)
    
    f = format_dense_regions
    dense_frozen_1s = f(find_dense_regions(frozen_bitset, bit_kind="1"))
    dense_frozen_0s = f(find_dense_regions(frozen_bitset, bit_kind="0"))
    dense_unchecked = f(find_dense_regions(sunset_bitset, bit_kind="0"))
    dense_checked = f(find_dense_regions(sunset_bitset, bit_kind="1"))
    print("0" in sunset_bitset)
    print(len(list(x for x in sunset_bitset if x == "0")))
    print(r.get("sunset_count"))

    html_content = f"""
    <html>
    <head>
        <style>
        li {{
            font-size: 2em;
        }}
        h2 {{ 
            font-size: 3em;
        }}
        .wrapper {{
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
        }}
        </style>
    </head>
    <body>
    <div class="wrapper">
    <h1>some numbers, updated sometimes</h1>
    <ul>
        <li class="lol-you-wish-there-was-information-here">{stats['frozen_count']}</li>
        <li>{stats['freeze_time_ms']}</li>
        <li>{" : ".join(map(str, sunset_streaks[0]))} | {" : ".join(map(str, sunset_streaks[1]))}</li>
        <li>{" : ".join(map(str, frozen_streaks[0]))} | {" : ".join(map(str, frozen_streaks[1]))}</li>
        <li>f {dense_frozen_1s}</li>
        <li>f {dense_frozen_0s}</li>
        <li>b {dense_checked}</li>
        <li>b {dense_unchecked}</li>
    </ul>
    </div>
    </body>
    </html>
    """

    with open("some-numbers.html", "w") as f:
        f.write(html_content)
