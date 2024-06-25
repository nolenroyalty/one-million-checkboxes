from flask import Flask, render_template, jsonify, request, send_from_directory, send_file
from flask_socketio import SocketIO
from flask_cors import CORS
import os
from apscheduler.schedulers.background import BackgroundScheduler
from bitarray import bitarray

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
else:
    # In-memory storage
    in_memory_storage = {'bitset': bitarray('0' * TOTAL_CHECKBOXES), 'count': 0}

    

def _redis_get_bit(index):
    adjusted_index = TOTAL_CHECKBOXES - 1 - index
    return bool(redis_client.getbit('bitset', adjusted_index))

def _redis_set_bit(index, value):
    adjusted_index = TOTAL_CHECKBOXES - 1 - index
    diff = redis_client.evalsha(set_bit_sha, 1, 'bitset', adjusted_index, int(value))
    return diff != 0

def _in_memory_get_bit(index):
    return bool(in_memory_storage['bitset'][index])

def _in_memory_set_bit(index, value):
    current_value = in_memory_storage['bitset'][index]
    if current_value != value:
        in_memory_storage['bitset'][index] = value
        in_memory_storage['count'] += 1 if value else -1
        return True
    return False

def get_bit(index):
    if USE_REDIS:
        return _redis_get_bit(index)
    else:
        return _in_memory_get_bit(index)

def set_bit(index, value):
    if USE_REDIS:
        _redis_set_bit(index, value)
    else:
        _in_memory_set_bit(index, value)

def create_rle_state():
    if USE_REDIS:
        # bitset = redis_client.get('bitset')
        count = int(redis_client.get('count') or 0)
        raw_bitset = redis_client.get('bitset')
        bitset = bitarray(endian='big')
        bitset.frombytes(raw_bitset)
    else:
        # bitset = in_memory_storage['bitset']
        count = in_memory_storage['count']
        bitset = in_memory_storage['bitset']
    
    bits_that_are_set = []
    start_index = -1
    if USE_REDIS:
        for i, bit in enumerate(bitset[::-1]):
            if bit and start_index == -1:
                start_index = i
            elif not bit and start_index != -1:
                bits_that_are_set.append((start_index, i - start_index))
                start_index = -1
    else:
        for i, bit in enumerate(bitset):
            if bit and start_index == -1:
                start_index = i
            elif not bit and start_index != -1:
                bits_that_are_set.append((start_index, i - start_index))
                start_index = -1

    if start_index != -1:
        bits_that_are_set.append((start_index, len(bitset) - start_index))
    
    return { 'setBits': bits_that_are_set, 'count': count }

@app.route('/api/initial-state')
def get_initial_state():
    state = create_rle_state()    
    return jsonify(state)

def emit_full_state():
    print("Emitting full state")
    socketio.emit('full_state', create_rle_state())

@app.route('/api/toggle/<int:index>', methods=['POST'])
def toggle_bit(index):
    current_value = get_bit(index)
    new_value = not current_value
    print(f"Setting bit {index} to {new_value} from {current_value}")
    set_bit(index, new_value)
    
    if USE_REDIS:
        count = int(redis_client.get('count') or 0)
    else:
        count = in_memory_storage['count']

    socketio.emit('bit_toggled', {'index': index, 'value': new_value})
    
    return jsonify({
        'index': index,
        'value': new_value,
        'count': count
    })


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

if __name__ == '__main__':
    set_bit(0, True)
    set_bit(1, True)
    set_bit(100, True)
    set_bit(101, True)
    emit_state_updates()
    socketio.run(app, port=5001)
