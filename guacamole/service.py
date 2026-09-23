import os
import requests
import base64
import time
from dotenv import load_dotenv

load_dotenv()

# ==============================
# CONFIG
# ==============================

GUAC_API_URL = os.getenv("GUACAMOLE_API")
GUAC_PUBLIC_URL = "https://guac.datacore.com.br/guacamole"

GUAC_ADMIN_USER = os.getenv("GUACAMOLE_USER")
GUAC_ADMIN_PASS = os.getenv("GUACAMOLE_PASSWORD")

GETIP_URL = "https://portal-dc.datacore.com.br/getip"

TEMP_PASSWORD = "Temp@1234!"

TIMEOUT = 5
RETRY = 2

GUAC_URL = GUAC_PUBLIC_URL
# ==============================
# UTIL
# ==============================

def log(msg):
    print(f"[GUAC] {msg}")


def _extract_username(email: str) -> str:
    return email.strip().split("@")[0].lower()


def _normalize_name(name: str) -> str:
    return name.strip().lower()


def encode_guac_id(connection_id: str, data_source: str) -> str:
    raw = f"{connection_id}\x00c\x00{data_source}"
    # ✅ urlsafe evita + e / que quebram a URL
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def gerar_link_conexao(connection_id: str, token_data: dict) -> str:
    encoded = encode_guac_id(connection_id, token_data["dataSource"])
    # ✅ sempre GUAC_PUBLIC_URL, nunca GUAC_API_URL
    return f"{GUAC_PUBLIC_URL}/#/client/{encoded}?token={token_data['authToken']}"

# ==============================
# REQUEST WRAPPER (com retry)
# ==============================

def request_with_retry(method, url, **kwargs):
    for attempt in range(RETRY + 1):
        try:
            r = requests.request(method, url, timeout=TIMEOUT, **kwargs)
            return r
        except requests.RequestException as e:
            log(f"Erro HTTP tentativa {attempt+1}: {e}")
            if attempt == RETRY:
                raise
            time.sleep(1)

# ==============================
# AUTENTICAÇÃO
# ==============================

def get_token() -> dict:
    log("Login admin")

    r = request_with_retry(
        "POST",
        f"{GUAC_API_URL}/api/tokens",
        data={
            "username": GUAC_ADMIN_USER,
            "password": GUAC_ADMIN_PASS,
        },
    )

    if r.status_code != 200:
        raise Exception(f"Erro token admin: {r.status_code} {r.text}")

    return r.json()


# ==============================
# HOSTS
# ==============================
def get_hosts() -> list:
    log("Buscando hosts")

    headers = {
        "Authorization": "Bearer SEU_TOKEN_AQUI"  # ajuste se necessário
    }

    r = request_with_retry(
        "GET",
        GETIP_URL,
        headers=headers,
    )

    if r.status_code != 200:
        raise Exception(f"Erro ao buscar hosts: {r.status_code} {r.text}")

    return r.json()


def get_user_token(username: str) -> dict:
    log(f"Login usuário: {username}")

    r = request_with_retry(
        "POST",
        f"{GUAC_API_URL}/api/tokens",
        data={
            "username": username,
            "password": TEMP_PASSWORD,
        },
    )

    if r.status_code != 200:
        raise Exception(f"Erro token usuário: {r.status_code} {r.text}")

    return r.json()


# ==============================
# CONEXÕES
# ==============================
def get_connections(token_data: dict) -> dict:
    r = request_with_retry(
        "GET",
        f"{GUAC_API_URL}/api/session/data/{token_data['dataSource']}/connections",
        params={"token": token_data["authToken"]},
    )

    if r.status_code != 200:
        raise Exception(f"Erro listar conexões: {r.status_code} {r.text}")

    return r.json() if isinstance(r.json(), dict) else {}


def find_connection_by_name(token_data: dict, name: str) -> str | None:
    target = _normalize_name(name)

    connections = get_connections(token_data)

    for conn_id, conn in connections.items():
        conn_name = _normalize_name(conn.get("name", ""))

        if conn_name == target:
            log(f"Conexão encontrada: {conn_name} ({conn_id})")
            return conn_id

    log(f"Conexão não encontrada: {target}")
    return None


def create_rdp_connection(token_data: dict, nome_host: str, porta: int | str) -> str:
    nome_host = _normalize_name(nome_host)

    payload = {
        "parentIdentifier": "ROOT",
        "name": nome_host,
        "protocol": "rdp",
        "parameters": {
            "hostname": "ts.datacore.com.br",
            "port": str(porta),
            "security": "any",
            "ignore-cert": "true",
        },
        "attributes": {},
    }

    log(f"Criando conexão: {nome_host}")

    r = request_with_retry(
        "POST",
        f"{GUAC_API_URL}/api/session/data/{token_data['dataSource']}/connections",
        params={"token": token_data["authToken"]},
        json=payload,
    )

    # 🔥 TRATAMENTO DE DUPLICIDADE
    if r.status_code == 400 and "already exists" in r.text:
        log("Conexão já existe (fallback ativado)")
        existing_id = find_connection_by_name(token_data, nome_host)
        if existing_id:
            return existing_id

    if r.status_code not in (200, 201):
        raise Exception(f"Erro criar conexão: {r.status_code} {r.text}")

    conn_id = r.json()["identifier"]
    log(f"Conexão criada: {conn_id}")

    return conn_id


# ==============================
# USUÁRIOS
# ==============================
def user_exists(token_data, username):
    r = request_with_retry(
        "GET",
        f"{GUAC_API_URL}/api/session/data/{token_data['dataSource']}/users/{username}",
        params={"token": token_data["authToken"]},
    )
    return r.status_code == 200


def create_user(token_data, username):
    log(f"Criando usuário: {username}")

    payload = {
        "username": username,
        "password": TEMP_PASSWORD,
        "attributes": {}
    }

    r = request_with_retry(
        "POST",
        f"{GUAC_API_URL}/api/session/data/{token_data['dataSource']}/users",
        params={"token": token_data["authToken"]},
        json=payload,
    )

    if r.status_code not in (200, 201):
        raise Exception(f"Erro criar usuário: {r.status_code} {r.text}")
    

def reset_user_password(token_data, username):
    payload = {
        "username": username,
        "password": TEMP_PASSWORD,
        "attributes": {}
    }

    r = request_with_retry(
        "PUT",
        f"{GUAC_API_URL}/api/session/data/{token_data['dataSource']}/users/{username}",
        params={"token": token_data["authToken"]},
        json=payload,
    )

    # ✅ agora loga erro se o reset falhar
    if r.status_code not in (200, 204):
        log(f"⚠️ Falha ao resetar senha de {username}: {r.status_code} {r.text}")
        raise Exception(f"Erro reset senha: {r.status_code} {r.text}")


def ensure_user_exists(token_data: dict, username: str):
    if not user_exists(token_data, username):
        create_user(token_data, username)

    reset_user_password(token_data, username)


# ==============================
# PERMISSÕES
# ==============================
def grant_connection_to_user(token_data: dict, username: str, connection_id: str):
    payload = [
        {
            "op": "add",
            "path": f"/connectionPermissions/{connection_id}",
            "value": "READ",
        }
    ]

    r = request_with_retry(
        "PATCH",
        f"{GUAC_API_URL}/api/session/data/{token_data['dataSource']}/users/{username}/permissions",
        params={"token": token_data["authToken"]},
        json=payload,
    )

    if r.status_code not in (200, 204, 409):
        raise Exception(f"Erro permissão: {r.status_code} {r.text}")


# ==============================
# FUNÇÃO PRINCIPAL
# ==============================
def conectar_ou_criar(hostname: str, porta: int | str, email: str) -> str:
    username = _extract_username(email)

    log(f"Iniciando conexão para {hostname} ({username})")

    admin_token = get_token()

    ensure_user_exists(admin_token, username)

    connection_id = find_connection_by_name(admin_token, hostname)

    if not connection_id:
        connection_id = create_rdp_connection(admin_token, hostname, porta)

    grant_connection_to_user(admin_token, username, connection_id)

    user_token = get_user_token(username)

    url = gerar_link_conexao(connection_id, user_token)

    log(f"URL gerada com sucesso")
    log(f"URL: {url}")
    return url