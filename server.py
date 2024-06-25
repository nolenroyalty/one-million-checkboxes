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

TOTAL_CHECKBOXES = 1_000_000
REACT_BUILD_DIRECTORY = os.path.abspath(os.path.join(os.path.dirname(__file__), 'dist'))

app = Flask(__name__, static_folder=REACT_BUILD_DIRECTORY)
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*")
scheduler = BackgroundScheduler()

# Configuration
USE_REDIS = os.environ.get('USE_REDIS', 'false').lower() == 'true'

if USE_REDIS:
    import redis
    redis_client = redis.Redis(
        host=os.environ.get('REDIS_HOST', 'localhost'),
        port=int(os.environ.get('REDIS_PORT', 6379)),
        username=os.environ.get('REDIS_USERNAME', 'default'),
        password=os.environ.get('REDIS_PASSWORD', ''),
        db=0,
        ssl=True
    )

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
        redis_client.publish('bit_toggle_channel', json.dumps({'index': index, 'value': new_value}))

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
        socketio.emit('bit_toggled', {'index': index, 'value': new_value})

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
    index = data['index']
    current_value = get_bit(index)
    new_value = not current_value
    print(f"Setting bit {index} to {new_value} from {current_value}")
    set_bit(index, new_value)
    
    emit_toggle(index, new_value)

@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def serve(path):
    if path != "" and os.path.exists(os.path.join(app.static_folder, path)):
        return send_from_directory(app.static_folder, path)
    else:
        return send_file(os.path.join(app.static_folder, 'index.html'))
    
def emit_state_updates():
    scheduler.add_job(emit_full_state, 'interval', seconds=5)
    scheduler.start()

emit_state_updates()

def handle_redis_messages():
    if USE_REDIS:
        message_count = 0
        while True:
            message = pubsub.get_message(timeout=0.01)
            if message is None:
                # No more messages available
                break

            if message['type'] == 'message':
                try:
                    data = json.loads(message['data'])
                    socketio.emit('bit_toggled', data)
                    message_count += 1
                except json.JSONDecodeError:
                    print(f"Failed to decode message: {message['data']}")

            # Process up to 100 messages per job execution to prevent long-running jobs
            if message_count >= 100:
                break

        if message_count > 0:
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
