import redis
from datetime import datetime, timedelta
import os

print(os.environ.get("REDIS_HOST"))
redis_client = redis.Redis(
    host=os.environ.get('REDIS_HOST', 'localhost'),
    port=int(os.environ.get('REDIS_PORT', 6379)),
    username=os.environ.get('REDIS_USERNAME', 'default'),
    password=os.environ.get('REDIS_PASSWORD', ''),
    db=0,
    ssl=True
)
print("connected to redis")

def cleanup_old_logs(days_to_keep=30):
    today = datetime.now().date()
    cutoff_date = today - timedelta(days=days_to_keep)

    print("before")
    keys = redis_client.keys("checkbox_logs:*")
    print("here")

    for key in keys:
        key_date = datetime.strptime(key.decode().split(':')[1], '%Y-%m-%d').date()
        if key_date < cutoff_date:
            redis_client.delete(key)
        else:
            # Keys are sorted, so if we find a key that's not old enough, we can stop
            break

# Run this script daily
cleanup_old_logs()
