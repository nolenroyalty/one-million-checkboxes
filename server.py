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

MAX_LOGS_PER_DAY = 200_000_000
TOTAL_CHECKBOXES = 1_000_000
REACT_BUILD_DIRECTORY = os.path.abspath(os.path.join(os.path.dirname(__file__), 'dist'))

app = Flask(__name__, static_folder=REACT_BUILD_DIRECTORY)
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*")
scheduler = BackgroundScheduler()

# Configuration
USE_REDIS = os.environ.get('USE_REDIS', 'false').lower() == 'true'

class RedisRateLimiter:
    def __init__(self, redis_client, limit, window):
        self.redis = redis_client
        self.limit = limit
        self.window = window

    def is_allowed(self, key: str) -> bool:
        pipe = self.redis.pipeline()
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
            max_connections=200  # Adjust this number based on your needs
            )

    redis_client = redis.Redis(connection_pool=pool)

    print("connected to redis")

    def initialize_redis():
        if not redis_client.exists('bitset'):
            redis_client.set('bitset', b'\x00' * (TOTAL_CHECKBOXES // 8))
        if not redis_client.exists('count'):
            redis_client.set('count', '0')

    initialize_redis()

    pubsub = redis_client.pubsub(ignore_subscribe_messages=True)
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
    set_bit_sha = redis_client.script_load(set_bit_script)

    def get_bit(index):
        return bool(redis_client.getbit('bitset', index))
    
    def set_bit(index, value):
        diff = redis_client.evalsha(set_bit_sha, 1, 'bitset', index, int(value))
        return diff != 0
    
    def get_full_state():
        raw_data = redis_client.get("bitset")
        return base64.b64encode(raw_data).decode('utf-8')

    def get_count():
        return int(redis_client.get('count') or 0)
    
    def emit_toggle(index, new_value):
        redis_client.publish('bit_toggle_channel', json.dumps([index, new_value]))

    one_second_limiter = RedisRateLimiter(redis_client, limit=7, window=1)
    fifteen_second_limiter = RedisRateLimiter(redis_client, limit=80, window=15)
    sixty_second_limiter = RedisRateLimiter(redis_client, limit=240, window=60)
    
    connection_limiter = RedisRateLimiter(redis_client, limit=20, window=15)

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
        in_memory_storage['bitset'][index] = value
        in_memory_storage['count'] += value - current

    def get_full_state():
        return base64.b64encode(in_memory_storage['bitset'].tobytes()).decode('utf-8')
    
    def get_count():
        return in_memory_storage['count']
    
    def emit_toggle(index, new_value):
        update = [[index], []] if new_value else [[], [index]]
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
    return {'full_state': full_state, 'count': count}

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
    count = get_count()
    if count >= 1_000_000:
        # print("DISABLED TOGGLE EXCEEDED MAX")
        return False
    
    index = data['index']
    current_value = get_bit(index)
    new_value = not current_value
    set_bit(index, new_value)
    forwarded_for = request.headers.get('X-Forwarded-For') or "UNKNOWN_IP"
    log_checkbox_toggle(forwarded_for, index, new_value)
    
    emit_toggle(index, new_value)

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

            if message_count >= 200:
                break

        if message_count > 0:
            true_updates = []
            false_updates = []
            for update in updates:
                index, value = update
                if value:
                    true_updates.append(index)
                else:
                    false_updates.append(index)
            to_broadcast = [true_updates, false_updates]

            socketio.emit('batched_bit_toggles', to_broadcast)
            print(f"Processed {message_count} messages")

def setup_redis_listener():
    if USE_REDIS:
        print("Redis listener job added to scheduler")
        scheduler.add_job(handle_redis_messages, 'interval', seconds=0.1)

setup_redis_listener()

if __name__ == '__main__':
    set_bit(0, True)
    set_bit(1, True)
    set_bit(100, True)
    set_bit(101, True)
    socketio.run(app, host="0.0.0.0", port=5001)
