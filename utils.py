from decimal import Decimal
from flask import request


def normalize_for_json(obj):
    """
    Docstring para normalize_for_json

    :param obj: Descrição
    """
    if isinstance(obj, dict):
        return {k: normalize_for_json(v) for k, v in obj.items()}

    if isinstance(obj, list):
        return [normalize_for_json(i) for i in obj]

    if isinstance(obj, Decimal):
        return float(obj)

    return obj

def get_client_ip():
    """
    Retorna o IP real do cliente que está acessando o portal.
    """
    forwarded = request.headers.get("X-Forwarded-For")

    if forwarded:
        return forwarded.split(",")[0].strip()

    return request.remote_addr