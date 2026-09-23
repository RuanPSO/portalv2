import mysql.connector
from mysql.connector import Error
from datetime import datetime
import os
from dotenv import load_dotenv
import uuid

load_dotenv()


# ===============================
# CONFIGURAÇÃO DE CONEXÃO
# ===============================
DB_CONFIG_DATA = {
    "host": os.getenv("HOST_DATAZBX"),
    "user": os.getenv("USER_DATAZBX"),
    "password": os.getenv("PASSWORD_DATAZBX"),
    "database": os.getenv("DATABASE_DATAZBX"),
    "port": "3306",
}


# ===============================
# CONEXÃO MYSQL
# ===============================
def bdmonitoramento():
    """
    Docstring para bdmonitoramento
    """
    try:
        conn = mysql.connector.connect(**DB_CONFIG_DATA)
        if conn.is_connected():
            print(" Conectado ao MySQL")
            return conn
    except Error as e:
        print(f" Erro de conexão: {e}")
        return None


# =========================================
# QUERY SQL INSERIR USUARIO NO BANCO LOCAL
# =========================================
SQL_INSERIR_USUARIO = """
    INSERT INTO users (
        azure_oid,
        name,
        email,
        job_title,
        department,
        first_login,
        last_login,
        last_activity,
        is_online
    ) VALUES (
        %s, %s, %s, %s, %s, %s, %s, %s, 1
    )
    ON DUPLICATE KEY UPDATE 
        name = VALUES(name),
        email = VALUES(email),
        job_title = VALUES(job_title),
        department = VALUES(department),
        last_login = NOW(),
        last_activity = NOW(),
        is_online = 1
"""


# adicionar usuario no banco de dados local
def funcmonitor(conn, user: dict):
    """
    Docstring para funcmonitor

    :param conn: Descrição
    :param user: Descrição
    :type user: dict
    """
    if not conn:
        raise RuntimeError("Conexão com banco é None")

    now = datetime.now()
    cursor = None

    try:
        cursor = conn.cursor()
        cursor.execute(
            SQL_INSERIR_USUARIO,
            (
                user["azure_oid"],
                user["name"],
                user["email"],
                user["job_title"],
                user["department"],
                now,
                now,
                now,
            ),
        )
        conn.commit()

    except mysql.connector.Error as err:
        print("Erro ao gravar usuário no banco:")
        print(err)

    finally:
        if cursor:
            cursor.close()


def buscar_usuario_por_oid(conn, azure_oid):
    """
    Docstring para buscar_usuario_por_oid

    :param conn: Descrição
    :param azure_oid: Descrição
    """
    query = """
        SELECT *
        FROM users
        WHERE azure_oid = %s
        LIMIT 1
    """
    cursor = conn.cursor(dictionary=True)
    cursor.execute(query, (azure_oid,))
    user = cursor.fetchone()
    cursor.close()
    return user


def atualizar_login_usuario(conn, user_id):
    """
    Docstring para atualizar_login_usuario

    :param conn: Descrição
    :param user_id: Descrição
    """
    query = """
        UPDATE users
        SET last_login = %s,
            last_activity = %s,
            is_online = 1
        WHERE id = %s
    """
    cursor = conn.cursor()
    cursor.execute(query, (datetime.now(), datetime.now(), user_id))
    conn.commit()
    cursor.close()


def atualizar_atividade_usuario(conn, user_id):
    """
    Docstring para atualizar_atividade_usuario

    :param conn: Descrição
    :param user_id: Descrição
    """
    query = """
        UPDATE users
        SET last_activity = %s
        WHERE id = %s
    """
    cursor = conn.cursor()
    cursor.execute(query, (datetime.now(), user_id))
    conn.commit()
    cursor.close()


def marcar_usuario_offline(conn, user_id):
    """
    Docstring para marcar_usuario_offline

    :param conn: Descrição
    :param user_id: Descrição
    """
    query = """
        UPDATE users
        SET is_online = 0
        WHERE id = %s
    """
    cursor = conn.cursor()
    cursor.execute(query, (user_id,))
    conn.commit()
    cursor.close()


def buscar_dados_usuario(conn, user_id):
    """
    Docstring para buscar_dados_usuario

    :param conn: Descrição
    :param user_id: Descrição
    """
    query = """
        SELECT
            u.name,
            u.email,
            u.job_title,
            u.department,
            u.is_online,
            u.last_activity,
            ps.login_at
        FROM users u
        LEFT JOIN portal_user_sessions ps
            ON ps.user_id = u.id
        WHERE u.id = %s
        ORDER BY ps.login_at DESC
        LIMIT 1
    """
    cursor = conn.cursor(dictionary=True)
    cursor.execute(query, (user_id,))
    data = cursor.fetchone()
    cursor.close()
    return data


# controles de sessoes
def criar_sessao_portal(conn, user_id, request):

    cursor = conn.cursor()

    # 🔥 1. FINALIZA sessões antigas abertas do usuário
    cursor.execute("""
        UPDATE portal_user_sessions
        SET
            is_active = 0,
            logout_at = NOW(),
            session_seconds = TIMESTAMPDIFF(SECOND, login_at, NOW())
        WHERE user_id = %s
        AND is_active = 1
    """, (user_id,))

    # 🔥 2. cria nova sessão limpa
    session_token = str(uuid.uuid4())

    query = """
        INSERT INTO portal_user_sessions (
            user_id, login_at, last_activity,
            ip_address, user_agent,
            session_token, is_active
        ) VALUES (%s,%s,%s,%s,%s,%s,1)
    """

    cursor.execute(
        query,
        (
            user_id,
            datetime.now(),
            datetime.now(),
            request.remote_addr,
            request.headers.get("User-Agent"),
            session_token,
        ),
    )

    conn.commit()

    session_id = cursor.lastrowid
    cursor.close()

    return session_id, session_token


def atualizar_atividade_sessao(conn, session_token):
    """
    Atualiza atividade da sessão + garante que só sessão ativa receba update
    """

    query = """
        UPDATE portal_user_sessions
        SET last_activity = NOW()
        WHERE session_token = %s
        AND is_active = 1
    """

    cursor = conn.cursor()
    cursor.execute(query, (session_token,))
    conn.commit()

    atualizado = cursor.rowcount  # 🔥 verifica se realmente atualizou
    cursor.close()

    return atualizado > 0


def validar_sessao(conn, session_token):
    """
    Docstring para validar_sessao

    :param conn: Descrição
    :param session_token: Descrição
    """
    query = """
        SELECT * FROM portal_user_sessions
        WHERE session_token = %s AND is_active = 1
        LIMIT 1
    """
    cursor = conn.cursor(dictionary=True)
    cursor.execute(query, (session_token,))
    sessao = cursor.fetchone()
    cursor.close()
    return sessao


def finalizar_sessao(conn, session_token):
    """
    Docstring para finalizar_sessao

    :param conn: Descrição
    :param session_token: Descrição
    """
    query = """
        UPDATE portal_user_sessions
        SET
            logout_at = %s,
            session_seconds = TIMESTAMPDIFF(SECOND, login_at, %s),
            is_active = 0
        WHERE session_token = %s
    """

    now = datetime.now()
    cursor = conn.cursor()
    cursor.execute(query, (now, now, session_token))
    conn.commit()
    cursor.close()


def usuarios_online(conn):
    """
    Docstring para usuarios_online

    :param conn: Descrição
    """
    query = """
        SELECT u.name, u.email, s.last_activity, s.ip_address
        FROM portal_user_sessions s
        JOIN users u ON u.id = s.user_id
        WHERE s.is_active = 1
        ORDER BY s.last_activity DESC
    """
    cursor = conn.cursor(dictionary=True)
    cursor.execute(query)
    data = cursor.fetchall()
    cursor.close()
    return data


def expirar_sessoes_inativas(conn, minutos=1):
    """
    Docstring para expirar_sessoes_inativas

    :param conn: Descrição
    :param minutos: Descrição
    """
    query = """
        UPDATE portal_user_sessions
        SET
            is_active = 0,
            logout_at = NOW(),
            session_seconds = TIMESTAMPDIFF(SECOND, login_at, NOW())
        WHERE is_active = 1
        AND last_activity < NOW() - INTERVAL %s MINUTE
    """
    cursor = conn.cursor()
    cursor.execute(query, (minutos,))
    conn.commit()
    cursor.close()


def registrar_logout(conn, user_id, session_token):
    """
    Docstring para registrar_logout

    :param conn: Descrição
    :param user_id: Descrição
    :param session_token: Descrição
    """

    try:
        # encerra sessão
        finalizar_sessao(conn, session_token)

        # marca usuário offline
        marcar_usuario_offline(conn, user_id)

    except mysql.connector.Error as err:
        print("Erro ao registrar logout:", err)

def salvar_auditoria_login(conn, user_id, ip, sistema, device_id, cidade, pais):
    """
    Salva log detalhado de login do Azure
    """

    cursor = conn.cursor()

    sql = """
        INSERT INTO auditoria_login (
            user_id,
            ip_address,
            sistema_operacional,
            device_id,
            cidade,
            pais,
            data_login
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s)
    """

    valores = (
        user_id,
        ip,
        sistema,
        device_id,
        cidade,
        pais,
        datetime.now()
    )

    cursor.execute(sql, valores)
    conn.commit()
    cursor.close()

    print("Login auditado com sucesso")



def update_user_theme(user_id, theme):
    conn = bdmonitoramento()
    if not conn:
        return False

    try:
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE users
            SET theme = %s,
                updated_at = NOW()
            WHERE id = %s
        """, (theme, user_id))

        conn.commit()
        return True

    except Error as e:
        print(f"Erro ao atualizar tema: {e}")
        return False

    finally:
        cursor.close()
        conn.close()


