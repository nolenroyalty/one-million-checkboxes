from flask import Flask, render_template, jsonify, request, send_from_directory, send_file
from flask_socketio import SocketIO
import os

REACT_BUILD_DIRECTORY = os.path.abspath(os.path.join(os.path.dirname(__file__), 'dist'))

app = Flask(__name__, static_folder=REACT_BUILD_DIRECTORY)
socketio = SocketIO(app)

# Configuration
USE_REDIS = os.environ.get('USE_REDIS', 'false').lower() == 'true'

if USE_REDIS:
    import redis
    redis_client = redis.Redis(host='localhost', port=6379, db=0)
else:
    # In-memory storage
    in_memory_storage = {'bitset': bytearray(1000000 // 8), 'count': 0}

def _redis_get_bit(index):
    byte_index = index // 8
    bit_index = index % 8
    byte = redis_client.getbit('bitset', byte_index)
    return (byte & (1 << bit_index)) != 0

def _redis_set_bit(index, value):
    byte_index = index // 8
    bit_index = index % 8
    if value:
        redis_client.setbit('bitset', index, 1)
        redis_client.set('count', int(redis_client.get('count') or 0) + 1)
    else:
        redis_client.setbit('bitset', index, 0)
        redis_client.set('count', int(redis_client.get('count') or 0) - 1)

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

@app.route('/api/toggle/<int:index>', methods=['POST'])
def toggle_bit(index):
    current_value = get_bit(index)
    new_value = not current_value
    set_bit(index, new_value)
    socketio.emit('bit_toggled', {'index': index, 'value': new_value})
    return jsonify({'success': True})


@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def serve(path):
    if path != "" and os.path.exists(os.path.join(app.static_folder, path)):
        return send_from_directory(app.static_folder, path)
    else:
        return send_file(os.path.join(app.static_folder, 'index.html'))

if __name__ == '__main__':
    socketio.run(app, debug=True)
