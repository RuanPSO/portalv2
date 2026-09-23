import redis
from redis import Redis
import os

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
REDIS_DB = int(os.getenv("REDIS_DB", 0))

redis_client = redis.Redis(
    host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB, decode_responses=True
)


def test_redis():
    try:
        redis_client.ping()
        print("Redis conectado com sucesso")
    except redis.exceptions.ConnectionError as e:
        print("Erro ao conectar no Redis:", e)
