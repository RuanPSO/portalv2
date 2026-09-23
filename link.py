import mysql.connector
from mysql.connector import Error
from dotenv import load_dotenv
import os
import json

# ===============================
# LOAD ENV
# ===============================
load_dotenv()

# ===============================
# CONFIG MYSQL
# ===============================
DB_CONFIG = {
    "host": os.getenv("DB_HOST"),
    "user": os.getenv("DB_USER"),
    "password": os.getenv("DB_PASSWORD"),
    "database": os.getenv("DB_NAME"),
    "port": "32059",
}

# ===============================
# CONEXÃO MYSQL
# ===============================
def conectar_mysql():

    try:

        conn = mysql.connector.connect(**DB_CONFIG)

        if not conn.is_connected():
            raise Exception("Falha conexão MySQL")

        print("[OK] Conectado ao MySQL")

        return conn

    except Error as e:

        print(f"[ERRO MYSQL] {e}")
        raise


# ===============================
# SERIALIZADOR JSON
# ===============================
def serializar(data):

    return json.loads(
        json.dumps(
            data,
            default=str
        )
    )


# ===============================
# HOSTS ICMP
# ===============================
def get_hosts_icmp(conn):

    cursor = conn.cursor(dictionary=True)

    query = """
        SELECT DISTINCT
            h.hostid,
            h.host,
            g.name AS grupo
        FROM hosts h

        JOIN hosts_groups hg
            ON hg.hostid = h.hostid

        JOIN hstgrp g
            ON g.groupid = hg.groupid

        WHERE h.status = 0

        AND LOWER(TRIM(g.name)) IN (

            'icmp',
            'icmp:ping',
            'icmp: icmp ping',
            'icmp: icmp loss',
            'icmp loss',
            'icmp response time'

        )

        ORDER BY h.host ASC
    """

    cursor.execute(query)

    data = cursor.fetchall()

    cursor.close()

    return serializar(data)


# ===============================
# TESTE
# ===============================
def testar():

    try:

        conn = conectar_mysql()

        hosts = get_hosts_icmp(conn)

        print("\n====================================")
        print(" HOSTS ICMP ENCONTRADOS ")
        print("====================================\n")

        if not hosts:

            print("Nenhum host encontrado.")

            return

        for host in hosts:

            print(
                f'[HOSTID: {host["hostid"]}] '
                f'{host["host"]} '
                f'-> Grupo: {host["grupo"]}'
            )

        print("\n====================================")
        print(f'TOTAL: {len(hosts)} hosts')
        print("====================================\n")

        conn.close()

    except Exception as e:

        print(f"\n[ERRO] {e}\n")


# ===============================
# MAIN
# ===============================
if __name__ == "__main__":

    testar()