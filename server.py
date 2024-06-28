import eventlet
eventlet.monkey_patch(thread=True, time=True)

from flask import Flask, render_template, jsonify, request, send_from_directory, send_file
from flask_socketio import SocketIO
from flask_cors import CORS
import os
from apscheduler.schedulers.background import BackgroundScheduler
from bitarray import bitarray
import base64
import json
import time
from datetime import datetime
from contextlib import contextmanager


MAX_LOGS_PER_DAY = 400_000_000
TOTAL_CHECKBOXES = 1_000_000
REACT_BUILD_DIRECTORY = os.path.abspath(os.path.join(os.path.dirname(__file__), 'dist'))
# I found this by portscanning my own VPC because the DNS record wouldn't work lmfao
REDIS_REPLICA_IP="10.108.0.13"

app = Flask(__name__, static_folder=REACT_BUILD_DIRECTORY)
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*")
scheduler = BackgroundScheduler()

# Configuration
USE_REDIS = os.environ.get('USE_REDIS', 'false').lower() == 'true'

class RedisRateLimiter:
    def __init__(self, pool, limit, window):
        self.pool = pool
        self.limit = limit
        self.window = window

    def is_allowed(self, key: str) -> bool:
        with get_redis_connection(self.pool) as redis_client:
            pipe = redis_client.pipeline()
            now = int(time.time())
            key = f'rate_limit:{key}:{self.window}'  # Include window in the key
            
            pipe.zadd(key, {now: now})
            pipe.zremrangebyscore(key, 0, now - self.window)
            pipe.zcard(key)
            pipe.expire(key, self.window)
            
            _, _, count, _ = pipe.execute()

            return count <= self.limit

if USE_REDIS:
    import redis
    from redis import ConnectionPool
       # Create a connection pool
    pool = ConnectionPool(
            host=os.environ.get('REDIS_HOST', 'localhost'),
            port=int(os.environ.get('REDIS_PORT', 6379)),
            username=os.environ.get('REDIS_USERNAME', 'default'),
            password=os.environ.get('REDIS_PASSWORD', ''),
            db=0,
            connection_class=redis.SSLConnection,
            max_connections=425  # Adjust this number based on your needs
            )
    
    replica_pool = ConnectionPool(
            host=REDIS_REPLICA_IP,
            port=int(os.environ.get('REDIS_PORT', 6379)),
            username=os.environ.get('REDIS_USERNAME', 'default'),
            password=os.environ.get('REDIS_PASSWORD', ''),
            db=0,
            connection_class=redis.SSLConnection,
            max_connections=425  # Adjust this number based on your needs
            )
    
    @contextmanager
    def get_redis_connection(pool):
        connection = redis.Redis(connection_pool=pool)
        try:
            yield connection
        finally:
            connection.close()

    # redis_client = redis.Redis(connection_pool=pool)
    # print("connected to redis")
    # replica_client = redis.Redis(connection_pool=replica_pool)
    # print("connected to replica")


    def initialize_redis():
        with get_redis_connection(pool) as redis_client:
            if not redis_client.exists('truncated_bitset'):
                redis_client.set('truncated_bitset', b'\x00' * (TOTAL_CHECKBOXES // 8))
            if not redis_client.exists('count'):
                redis_client.set('count', '0')

    initialize_redis()

    # pubsub = replica_client.pubsub(ignore_subscribe_messages=True)
    pubsub = redis.Redis(connection_pool=replica_pool).pubsub(ignore_subscribe_messages=True)
    pubsub.subscribe('bit_toggle_channel')

    # Lua script for atomic bit setting and count update
    set_bit_script = """
    local key = KEYS[1]
    local index = tonumber(ARGV[1])
    local value = tonumber(ARGV[2])
    local current = redis.call('getbit', key, index)
    local diff = value - current
    redis.call('setbit', key, index, value)
    redis.call('incrby', 'count', diff)
    return diff"""

    new_set_bit_script="""
    local key = KEYS[1]
    local count_key = KEYS[2]
    local index = tonumber(ARGV[1])
    local max_count = tonumber(ARGV[2])

    local current_count = tonumber(redis.call('get', count_key) or "0")
    if current_count >= max_count then
        return {redis.call('getbit', key, index), 0}  -- Return current count, current bit value, and 0 to indicate no change
    end

    local current_bit = redis.call('getbit', key, index)
    local new_bit = 1 - current_bit  -- Toggle the bit
    local diff = new_bit - current_bit

    if diff > 0 and current_count + diff > max_count then
        return { current_bit, 0}  -- Return current count, current bit value, and 0 to indicate no change
    end

    redis.call('setbit', key, index, new_bit)
    local new_count = current_count + diff
    redis.call('set', count_key, new_count)

    return {new_bit, diff}  -- new bit value, and the change (1, 0, or -1)"""

    # set_bit_sha = redis_client.script_load(set_bit_script)
    # new_set_bit_sha = redis_client.script_load(new_set_bit_script)
    with get_redis_connection(pool) as redis_client:
        new_set_bit_sha = redis_client.script_load(new_set_bit_script)

    def get_bit(index):
        with get_redis_connection(pool) as redis_client:
            return bool(redis_client.getbit('truncated_bitset', index))
    
    def set_bit(index, value):
        with get_redis_connection(pool) as redis_client:
            [_count, diff] = redis_client.evalsha(new_set_bit_sha, 1, 'truncated_bitset', index, int(value))
            return diff != 0

    def _toggle_internal(index):
        with get_redis_connection(pool) as redis_client:
            result = redis_client.evalsha(
                new_set_bit_sha, 
                2,  # number of keys
                'truncated_bitset',  # key for bitset
                'count',  # key for count
                index,  # index to toggle
                TOTAL_CHECKBOXES  # max count
            )
            new_bit_value, diff = result
            if diff == 0:
                return [False, None]
            return [True, new_bit_value]
    
    def get_full_state():
        with get_redis_connection(replica_pool) as replica_client:
            raw_data = replica_client.get("truncated_bitset")
            return base64.b64encode(raw_data).decode('utf-8')

    def get_count():
        with get_redis_connection(replica_pool) as replica_client:
            return int(replica_client.get('count') or 0)
    
    def emit_toggle(index, new_value, timestamp):
        with get_redis_connection(pool) as redis_client:
            redis_client.publish('bit_toggle_channel', json.dumps([index, new_value, timestamp]))

    one_second_limiter = RedisRateLimiter(pool, limit=7, window=1)
    fifteen_second_limiter = RedisRateLimiter(pool, limit=80, window=15)
    sixty_second_limiter = RedisRateLimiter(pool, limit=240, window=60)
    
    connection_limiter = RedisRateLimiter(pool, limit=20, window=15)

    limiters = [one_second_limiter, fifteen_second_limiter, sixty_second_limiter]

    def allow_toggle(key):
        return all(limiter.is_allowed(key) for limiter in limiters)
    
    def allow_connection(key):
        return connection_limiter.is_allowed(key)

    def log_checkbox_toggle(remote_ip, checkbox_index, checked_state):
        timestamp = datetime.now().isoformat()
        log_entry = f"{timestamp}|{remote_ip}|{checkbox_index}|{checked_state}"

        # Use the current date as part of the key
        key = f"checkbox_logs:{datetime.now().strftime('%Y-%m-%d')}"
        with get_redis_connection(pool) as redis_client:
            pipeline = redis_client.pipeline()
            pipeline.rpush(key, log_entry)
            pipeline.ltrim(key, 0, MAX_LOGS_PER_DAY - 1)
            pipeline.execute()

else:
    # In-memory storage
    in_memory_storage = {'bitset': bitarray('0' * TOTAL_CHECKBOXES), 'count': 0}

    def get_bit(index):
        return bool(in_memory_storage['bitset'][index])

    def set_bit(index, value):
        current = in_memory_storage['bitset'][index]
        count = in_memory_storage['count']
        if count >= TOTAL_CHECKBOXES:
            return False
        
        in_memory_storage['bitset'][index] = value
        in_memory_storage['count'] += value - current
        return True
    
    def _toggle_internal(index):
        print("here")
        current = in_memory_storage['bitset'][index]
        count = in_memory_storage['count']
        if count >= TOTAL_CHECKBOXES:
            return [False, None]
        
        new_value = not current
        in_memory_storage['bitset'][index] = new_value
        in_memory_storage['count'] += 1 if new_value else -1
        return [True, new_value]

    def get_full_state():
        return base64.b64encode(in_memory_storage['bitset'].tobytes()).decode('utf-8')
    
    def get_count():
        return in_memory_storage['count']
    
    def emit_toggle(index, new_value, timestamp):
        update = [[index], [], timestamp] if new_value else [[], [index], timestamp]
        socketio.emit('batched_bit_toggles', update)
    
    limiters = []

    def allow_toggle(key):
        return True
    
    def allow_connection(key):
        return True

    def log_checkbox_toggle(remote_ip, checkbox_index, checked_state):
        pass

def state_snapshot():
    full_state = get_full_state()
    count = get_count()
    timestamp = int(time.time() * 1000)  # Current time in milliseconds
    return {'full_state': full_state, 'count': count, "timestamp": timestamp}

@app.route('/api/initial-state')
def get_initial_state():
    return jsonify(state_snapshot())

def emit_full_state():
    print("Emitting full state")
    socketio.emit('full_state', state_snapshot())


@socketio.on('toggle_bit')
def handle_toggle(data):
    if not allow_toggle(request.sid):
        print(f"Rate limiting toggle request for {request.sid}")
        return False
    
    index = data['index']
    if index >= TOTAL_CHECKBOXES:
        return False
    
    did_toggle, new_value = _toggle_internal(index)
    timestamp = int(time.time() * 1000)  # Current time in milliseconds

    if did_toggle != 0:
        forwarded_for = request.headers.get('X-Forwarded-For') or "UNKNOWN_IP"
        log_checkbox_toggle(forwarded_for, index, new_value)
        emit_toggle(index, new_value, timestamp)

@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def serve(path):
    if path != "" and os.path.exists(os.path.join(app.static_folder, path)):
        return send_from_directory(app.static_folder, path)
    else:
        return send_file(os.path.join(app.static_folder, 'index.html'))
    

#@socketio.on('connect')
#def handle_connect():
    #forwarded_for = request.headers.get('X-Forwarded-For') or request.remote_addr
    #if forwarded_for and allow_connection(forwarded_for):
        #return True
    #else:
        #print(f"Rate limiting connection for {forwarded_for}")
        #return False

def emit_state_updates():
    scheduler.add_job(emit_full_state, 'interval', seconds=45)
    scheduler.start()

emit_state_updates()

def handle_redis_messages():
    if USE_REDIS:
        message_count = 0
        updates = []
        while True:
            message = pubsub.get_message(timeout=0.01)
            if message is None:
                # No more messages available
                break

            if message['type'] == 'message':
                try:
                    data = json.loads(message['data'])
                    updates.append(data)
                    message_count += 1
                except json.JSONDecodeError:
                    print(f"Failed to decode message: {message['data']}")

            if message_count >= 600:
                break

        if message_count > 0:
            true_updates = []
            false_updates = []
            max_timestamp = 0
            for update in updates:
                if len(update) != 3: # backwards compatibility
                    continue
                else:
                    index, value, timestamp = update
                    max_timestamp = max(max_timestamp, timestamp)
                if value:
                    true_updates.append(index)
                else:
                    false_updates.append(index)
            to_broadcast = [true_updates, false_updates, max_timestamp]

            socketio.emit('batched_bit_toggles', to_broadcast)
            # print(f"Processed {message_count} messages")

def setup_redis_listener():
    if USE_REDIS:
        print("Redis listener job added to scheduler")
        scheduler.add_job(handle_redis_messages, 'interval', seconds=0.2)

setup_redis_listener()

if __name__ == '__main__':
    set_bit(0, True)
    set_bit(1, True)
    set_bit(100, True)
    set_bit(101, True)

    socketio.run(app, host="0.0.0.0", port=5001)
