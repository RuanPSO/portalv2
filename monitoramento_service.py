import requests

GUAC_URL = "https://portal-dc.datacore.com.br/guacamole"

def get_active_connections(token, data_source):
    url = f"{GUAC_URL}/api/session/data/{data_source}/activeConnections"

    headers = {
        "Guacamole-Token": token
    }

    response = requests.get(url, headers=headers)

    if response.status_code != 200:
        return []

    return response.json()

def correlacionar_usuarios(db_users, guac_connections):
    resultado = []

    for conn_id, conn in guac_connections.items():
        username = conn.get("username")

        user = next(
            (u for u in db_users if u["email"] == username),
            None
        )

        resultado.append({
            "user": user,
            "connection": conn
        })

    return resultado
