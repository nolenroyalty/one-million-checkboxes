from flask import Flask, render_template, jsonify, request, send_from_directory, send_file
from flask_socketio import SocketIO
from flask_cors import CORS
import os
from apscheduler.schedulers.background import BackgroundScheduler


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
    redis_client = redis.Redis(host='localhost', port=6379, db=0)
else:
    # In-memory storage
    in_memory_storage = {'bitset': bytearray(1000000 // 8), 'count': 0}

def _redis_get_bit(index):
    return bool(redis_client.getbit('bitset', index))


def _redis_set_bit(index, value):
    redis_client.setbit('bitset', index, value)
    redis_client.set('count', int(redis_client.get('count') or 0) + (1 if value else -1))

def _in_memory_get_bit(index):
    byte_index = index // 8
    bit_index = index % 8
    return (in_memory_storage['bitset'][byte_index] & (1 << bit_index)) != 0

def _in_memory_set_bit(index, value):
    byte_index = index // 8
    bit_index = index % 8
    if value:
        in_memory_storage['bitset'][byte_index] |= (1 << bit_index)
        in_memory_storage['count'] += 1
    else:
        in_memory_storage['bitset'][byte_index] &= ~(1 << bit_index)
        in_memory_storage['count'] -= 1

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


@app.route('/api/bitset', methods=['GET'])
def get_bitset():
    if USE_REDIS:
        bitset = redis_client.get('bitset')
        count = int(redis_client.get('count') or 0)
    else:
        bitset = in_memory_storage['bitset']
        count = in_memory_storage['count']
    return jsonify({'bitset': bitset.hex(), 'count': count})

def create_rle_state():
    if USE_REDIS:
        # bitset = redis_client.get('bitset')
        count = int(redis_client.get('count') or 0)
    else:
        # bitset = in_memory_storage['bitset']
        count = in_memory_storage['count']
    
    bits_that_are_set = []
    start_index = 0
    set_count = 0
    for i in range(TOTAL_CHECKBOXES):
        if get_bit(i) and set_count > 0:
            set_count += 1
        elif get_bit(i) and set_count == 0:
            start_index = i
            set_count = 1
        elif not get_bit(i) and set_count > 0:
            bits_that_are_set.append((start_index, set_count))
            set_count = 0
    if set_count > 0:
        bits_that_are_set.append((start_index, set_count))
    
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
    

scheduler.add_job(emit_full_state, 'interval', seconds=5)
scheduler.start()

if __name__ == '__main__':
    set_bit(0, True)
    set_bit(1, True)
    set_bit(100, True)
    set_bit(101, True)
    socketio.run(app, host="0.0.0.0", port=5001)
