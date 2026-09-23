# ============================================================
# consulta.py / data.py
# ============================================================
# Acesso PostgreSQL para Zabbix 7.0
#
# Compatível com:
#   - PostgreSQL
#   - Zabbix 7.0
#   - psycopg2
#   - Redis
#
# Mantém a compatibilidade com as funções utilizadas
# anteriormente pelo portal Flask.
# ============================================================

import os
import json
import time

from datetime import datetime, date, timedelta
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv
from cache import redis_client

# ============================================================
# ENV
# ============================================================

load_dotenv()


# ============================================================
# CACHE LOCAL
# ============================================================

HOST_METRICS_CACHE = {}

CACHE_TTL = 6


# ============================================================
# CONFIGURAÇÃO POSTGRESQL
# ============================================================

DB_CONFIG = {
    "host": os.getenv("DB_HOST"),
    "user": os.getenv("DB_USER"),
    "password": os.getenv("DB_PASSWORD"),
    "dbname": os.getenv("DB_NAME"),
    "port": os.getenv("DB_PORT", "5432"),
}


# ============================================================
# CONEXÃO POSTGRESQL
# ============================================================

def conectar_postgres():
    """
    Abre uma conexão com o PostgreSQL.

    Compatível com PostgreSQL direto ou PgBouncer.
    """

    try:

        conn = psycopg2.connect(
            host=DB_CONFIG["host"],
            user=DB_CONFIG["user"],
            password=DB_CONFIG["password"],
            dbname=DB_CONFIG["dbname"],
            port=DB_CONFIG["port"],
            connect_timeout=10,
        )

        return conn

    except psycopg2.Error as e:

        print(f"[POSTGRES] Erro de conexão: {e}")

        raise

# ============================================================
# COMPATIBILIDADE
# ============================================================

def conectar_mysql():
    """
    Compatibilidade com código antigo.

    Agora conecta no PostgreSQL.
    """
    return conectar_postgres()

# ============================================================
# SERIALIZAÇÃO
# ============================================================

def serializar(resultados):
    """
    Converte tipos PostgreSQL/Python para valores
    que podem ser serializados em JSON.
    """

    if resultados is None:
        return resultados

    for row in resultados:

        if not hasattr(row, "items"):
            continue

        for key, value in row.items():

            if isinstance(value, datetime):
                row[key] = value.isoformat()

            elif isinstance(value, date):
                row[key] = value.isoformat()

            elif isinstance(value, timedelta):

                total = int(value.total_seconds())

                horas = total // 3600
                minutos = (total % 3600) // 60
                segundos = total % 60

                row[key] = (
                    f"{horas:02d}:"
                    f"{minutos:02d}:"
                    f"{segundos:02d}"
                )

    return resultados


# ============================================================
# QUERY: HOSTS ATIVOS
# ============================================================

def get_hosts(conn):

    query = """
        SELECT
            h.hostid,
            h.host,
            i.ip
        FROM hosts h
        LEFT JOIN interface i
               ON i.hostid = h.hostid
              AND i.main = 1
        WHERE h.status = 0
        ORDER BY h.host
    """

    cursor = conn.cursor(cursor_factory=RealDictCursor)

    try:

        cursor.execute(query)

        data = cursor.fetchall()

        return serializar(data)

    finally:

        cursor.close()

# ============================================================
# QUERY: ITENS
# ============================================================

def get_itens(conn):

    query = """
        SELECT
            h.host,
            i.name AS item,
            i.key_
        FROM items i
        JOIN hosts h
          ON h.hostid = i.hostid
        WHERE i.status = 0
        LIMIT 10
    """

    cursor = conn.cursor(cursor_factory=RealDictCursor)

    try:

        cursor.execute(query)

        data = cursor.fetchall()

        return serializar(data)

    finally:

        cursor.close()


# ============================================================
# HOST NAME
# ============================================================

def get_host_name(cursor, hostid):

    cursor.execute(
        """
        SELECT host
        FROM hosts
        WHERE hostid = %s
        LIMIT 1
        """,
        (hostid,),
    )

    row = cursor.fetchone()

    return row["host"] if row else None


# ============================================================
# SERVIÇOS / TRIGGERS ATIVOS
# ============================================================

def get_active_services(cursor, hostid):

    cursor.execute(
        """
        SELECT DISTINCT
            t.triggerid,
            t.description,
            t.priority AS severity
        FROM triggers t
        JOIN functions f
          ON f.triggerid = t.triggerid
        JOIN items i
          ON i.itemid = f.itemid
        WHERE i.hostid = %s
          AND t.status = 0
          AND t.priority >= 2
        ORDER BY
            t.priority DESC,
            t.description
        """,
        (hostid,),
    )

    rows = cursor.fetchall()

    return [
        {
            "id": row["triggerid"],
            "description": row["description"],
            "severity": int(row["severity"]),
        }
        for row in rows
    ]

# ============================================================
# CPU LINUX
# ============================================================

def get_cpu_linux_single(cursor, hostid):

    cursor.execute(
        """
        WITH latest AS (
            SELECT DISTINCT ON (i.itemid)
                i.itemid,
                i.key_,
                h.value,
                h.clock
            FROM items i
            JOIN history h
                ON h.itemid = i.itemid
            WHERE i.hostid = %s
              AND i.key_ = 'system.cpu.util[,idle]'
            ORDER BY
                i.itemid,
                h.clock DESC
        )

        SELECT
            h.host,

            ROUND(
                (100 - latest.value)::numeric,
                2
            ) AS cpu_used,

            ROUND(
                latest.value::numeric,
                2
            ) AS cpu_free,

            to_timestamp(latest.clock) AS data

        FROM latest

        JOIN hosts h
            ON h.hostid = %s

        LIMIT 1
        """,
        (hostid, hostid),
    )

    row = cursor.fetchone()

    if not row:
        return None

    if row["cpu_used"] is None or row["cpu_free"] is None:
        return None

    return {
        "host": row["host"],
        "used": float(row["cpu_used"]),
        "free": float(row["cpu_free"]),
        "total": 100,
        "source": "linux",
        "data": row["data"],
    }
# ============================================================
# CPU - LINUX / WINDOWS
# Mantém o mesmo retorno esperado pelo frontend
# ============================================================

def get_cpu_usage(cursor, hostid, os_type=None):

    cursor.execute(
        """
        WITH latest AS (
            SELECT DISTINCT ON (i.key_)
                i.itemid,
                i.key_,
                h.value,
                h.clock
            FROM items i
            JOIN history h
                ON h.itemid = i.itemid
            WHERE i.hostid = %s
              AND i.key_ IN (
                  'system.cpu.util',
                  'system.cpu.util[,idle]'
              )
            ORDER BY
                i.key_,
                h.clock DESC
        )

        SELECT
            MAX(value) FILTER (
                WHERE key_ = 'system.cpu.util'
            ) AS cpu_used,

            MAX(value) FILTER (
                WHERE key_ = 'system.cpu.util[,idle]'
            ) AS cpu_idle,

            MAX(clock) AS clock

        FROM latest
        """,
        (hostid,),
    )

    row = cursor.fetchone()

    # --------------------------------------------------------
    # Sem dados
    # Mantém exatamente o contrato anterior
    # --------------------------------------------------------

    if not row:
        return {
            "used": None,
            "free": None,
            "total": 100,
            "source": "no_data",
        }

    # --------------------------------------------------------
    # CPU usada diretamente
    # system.cpu.util
    # --------------------------------------------------------

    if row["cpu_used"] is not None:

        used = float(row["cpu_used"])

        # Mantém a identificação anterior
        if os_type:
            source = os_type.lower()
        else:
            source = "windows_perf"

    # --------------------------------------------------------
    # CPU livre
    # system.cpu.util[,idle]
    # --------------------------------------------------------

    elif row["cpu_idle"] is not None:

        idle = float(row["cpu_idle"])

        used = 100 - idle

        # Mantém a identificação anterior
        if os_type:
            source = os_type.lower()
        else:
            source = "linux_idle"

    # --------------------------------------------------------
    # Nenhum item encontrado
    # --------------------------------------------------------

    else:

        return {
            "used": None,
            "free": None,
            "total": 100,
            "source": "no_data",
        }

    # --------------------------------------------------------
    # Proteção contra valores inválidos
    # --------------------------------------------------------

    used = min(max(used, 0), 100)

    free = 100 - used

    free = min(max(free, 0), 100)

    # --------------------------------------------------------
    # Mesmo retorno utilizado anteriormente pelo frontend
    # --------------------------------------------------------

    return {
        "used": round(used, 2),
        "free": round(free, 2),
        "total": 100,
        "source": source,
    }

# ============================================================
# PROBLEMAS ATIVOS
# ============================================================

def get_problemas(conn):

    query = """
        SELECT
            h.host,
            t.description,
            p.severity,
            to_timestamp(p.clock) AS inicio

        FROM problem p

        JOIN triggers t
          ON t.triggerid = p.objectid

        JOIN functions f
          ON f.triggerid = t.triggerid

        JOIN items i
          ON i.itemid = f.itemid

        JOIN hosts h
          ON h.hostid = i.hostid

        WHERE p.r_eventid IS NULL

        ORDER BY p.clock DESC

        LIMIT 5
    """

    cursor = conn.cursor(cursor_factory=RealDictCursor)

    try:

        cursor.execute(query)

        data = cursor.fetchall()

        return serializar(data)

    finally:

        cursor.close()


# ============================================================
# MAIN
# ============================================================

def main():

    conn = conectar_postgres()

    try:

        cursor = conn.cursor(cursor_factory=RealDictCursor)

        try:

            resultado = {
                "hosts": get_hosts(conn),
                "itens": get_itens(conn),
                "cpu": [],
                "problemas": get_problemas(conn),
                "coletado_em": datetime.now().isoformat(),
            }

        finally:

            cursor.close()

        return resultado

    finally:

        conn.close()


# ============================================================
# COLETAR DADOS
# ============================================================

def coletar_dados():

    conn = conectar_postgres()

    try:

        cursor = conn.cursor(cursor_factory=RealDictCursor)

        try:

            resultado = {
                "hosts": get_hosts(conn),
                "itens": get_itens(conn),
                "cpu": [],
                "problemas": get_problemas(conn),
                "status_hosts": get_status_ping_uptime_all(cursor),
                "coletado_em": datetime.now().isoformat(),
            }

            return resultado

        finally:

            cursor.close()

    finally:

        conn.close()


# ============================================================
# GRUPOS COM HOSTS
# ============================================================

def get_grupos_com_hosts():

    conn = conectar_postgres()

    try:

        query = """
            SELECT
                g.groupid,
                g.name AS grupo,
                h.hostid,
                h.host AS hostname

            FROM hstgrp g

            JOIN hosts_groups hg
              ON hg.groupid = g.groupid

            JOIN hosts h
              ON h.hostid = hg.hostid

            WHERE h.status = 0

            ORDER BY
                g.name,
                h.host
        """

        cursor = conn.cursor(cursor_factory=RealDictCursor)

        try:

            cursor.execute(query)

            rows = cursor.fetchall()

        finally:

            cursor.close()

    finally:

        conn.close()

    grupos = []

    grupos_map = {}

    for row in rows:

        groupid = row["groupid"]

        if groupid not in grupos_map:

            grupo_obj = {
                "groupid": groupid,
                "grupo": row["grupo"],
                "hosts": [],
            }

            grupos_map[groupid] = grupo_obj

            grupos.append(grupo_obj)

        grupos_map[groupid]["hosts"].append(
            {
                "hostid": row["hostid"],
                "hostname": row["hostname"],
            }
        )

    return grupos

# ============================================================
# DETECTAR SISTEMA OPERACIONAL
# ZABBIX 7.4 / POSTGRESQL
# ============================================================

def detectar_so(cursor, hostid):

    os_info = {
        "type": "unknown",
        "name": None,
        "kernel": None,
        "architecture": None,
    }

    print(f"[SO] detectando hostid={hostid}")

    # ========================================================
    # 1. system.sw.os
    # ========================================================

    cursor.execute(
        """
        SELECT
            i.itemid,
            i.key_,
            i.value_type
        FROM items i
        WHERE i.hostid = %s
          AND i.key_ = 'system.sw.os'
        LIMIT 1
        """,
        (hostid,),
    )

    item = cursor.fetchone()

    if item:

        print(
            f"[SO] encontrado system.sw.os "
            f"itemid={item['itemid']} "
            f"value_type={item['value_type']}"
        )

        value = None

        # ----------------------------------------------------
        # STRING
        # value_type = 2
        # ----------------------------------------------------

        if item["value_type"] == 2:

            cursor.execute(
                """
                SELECT value
                FROM history_str
                WHERE itemid = %s
                ORDER BY clock DESC
                LIMIT 1
                """,
                (item["itemid"],),
            )

            row = cursor.fetchone()

            if row:
                value = row["value"]

        # ----------------------------------------------------
        # TEXT
        # value_type = 4
        # ----------------------------------------------------

        elif item["value_type"] == 4:

            cursor.execute(
                """
                SELECT value
                FROM history_text
                WHERE itemid = %s
                ORDER BY clock DESC
                LIMIT 1
                """,
                (item["itemid"],),
            )

            row = cursor.fetchone()

            if row:
                value = row["value"]

        if value:

            value = str(value).strip()

            print(f"[SO] system.sw.os = {value}")

            os_info["name"] = value

            if "windows" in value.lower():

                os_info["type"] = "windows"

            else:

                os_info["type"] = "linux"

            return os_info

    # ========================================================
    # 2. system.uname
    # ========================================================

    print(f"[SO] tentando system.uname hostid={hostid}")

    cursor.execute(
        """
        SELECT
            i.itemid,
            i.key_,
            i.value_type
        FROM items i
        WHERE i.hostid = %s
          AND i.key_ = 'system.uname'
        LIMIT 1
        """,
        (hostid,),
    )

    item = cursor.fetchone()

    if item:

        print(
            f"[SO] encontrado system.uname "
            f"itemid={item['itemid']} "
            f"value_type={item['value_type']}"
        )

        value = None

        # ----------------------------------------------------
        # STRING
        # ----------------------------------------------------

        if item["value_type"] == 2:

            cursor.execute(
                """
                SELECT value
                FROM history_str
                WHERE itemid = %s
                ORDER BY clock DESC
                LIMIT 1
                """,
                (item["itemid"],),
            )

            row = cursor.fetchone()

            if row:
                value = row["value"]

        # ----------------------------------------------------
        # TEXT
        # ----------------------------------------------------

        elif item["value_type"] == 4:

            cursor.execute(
                """
                SELECT value
                FROM history_text
                WHERE itemid = %s
                ORDER BY clock DESC
                LIMIT 1
                """,
                (item["itemid"],),
            )

            row = cursor.fetchone()

            if row:
                value = row["value"]

        if value:

            uname = str(value).strip()

            print(f"[SO] system.uname = {uname}")

            os_info["type"] = "linux"
            os_info["name"] = "Linux"
            os_info["kernel"] = uname

            parts = uname.split()

            if parts:
                os_info["architecture"] = parts[-1]

            return os_info

    # ========================================================
    # 3. FALLBACK PELOS ITENS
    # ========================================================

    print(f"[SO] tentando fallback hostid={hostid}")

    cursor.execute(
        """
        SELECT
            key_
        FROM items
        WHERE hostid = %s
          AND (
                key_ LIKE 'vfs.fs.size[C:%%'
                OR key_ LIKE 'perf_counter[%%'
                OR key_ LIKE 'perf_counter_en[%%'
                OR key_ LIKE 'system.cpu.util[%%'
              )
        LIMIT 1
        """,
        (hostid,),
    )

    row = cursor.fetchone()

    if row:

        key = str(row["key_"])

        print(
            f"[SO] fallback Windows pelo item: {key}"
        )

        os_info["type"] = "windows"
        os_info["name"] = "Windows"

        return os_info

    # ========================================================
    # 4. FALLBACK LINUX
    # ========================================================

    cursor.execute(
        """
        SELECT
            key_
        FROM items
        WHERE hostid = %s
          AND (
                key_ LIKE 'system.cpu%%'
                OR key_ LIKE 'vfs.fs%%'
                OR key_ LIKE 'vm.memory%%'
              )
        LIMIT 1
        """,
        (hostid,),
    )

    row = cursor.fetchone()

    if row:

        key = str(row["key_"])

        print(
            f"[SO] fallback Linux pelo item: {key}"
        )

        os_info["type"] = "linux"
        os_info["name"] = "Linux"

        return os_info

    # ========================================================
    # 5. DESCONHECIDO
    # ========================================================

    print(
        f"[SO] NÃO FOI POSSÍVEL DETECTAR "
        f"hostid={hostid}"
    )

    return os_info
# ============================================================
# DISCOS WINDOWS
# ============================================================

def buscar_discos_windows(cursor, hostid):

    cursor.execute(
        """
        WITH filesystems AS (

            SELECT
                it.hostid,
                it.itemid,

                split_part(
                    split_part(
                        it.key_,
                        '[',
                        2
                    ),
                    ',',
                    1
                ) AS mount

            FROM items it

            WHERE it.hostid = %s
              AND it.key_ LIKE 'vfs.fs.size[%%,total]'

        )

        SELECT
            fs.mount,

            -- ================================================
            -- TOTAL
            -- ================================================

            ROUND(
                (
                    total.value::numeric
                    / 1024
                    / 1024
                    / 1024
                ),
                2
            ) AS total_gb,

            -- ================================================
            -- USADO
            -- ================================================

            ROUND(
                (
                    used.value::numeric
                    / 1024
                    / 1024
                    / 1024
                ),
                2
            ) AS used_gb,

            -- ================================================
            -- DISPONÍVEL
            -- ================================================

            ROUND(
                (
                    (
                        total.value::numeric
                        - used.value::numeric
                    )
                    / 1024
                    / 1024
                    / 1024
                ),
                2
            ) AS free_gb,

            -- ================================================
            -- PERCENTUAL DE USO
            -- ================================================

            ROUND(
                percent.value::numeric,
                2
            ) AS percent

        FROM filesystems fs

        -- ====================================================
        -- TOTAL
        -- ====================================================

        JOIN LATERAL (

            SELECT value

            FROM history_uint

            WHERE itemid = fs.itemid

            ORDER BY clock DESC

            LIMIT 1

        ) total ON TRUE

        -- ====================================================
        -- USED
        -- ====================================================

        JOIN items iu

          ON iu.hostid = fs.hostid

         AND iu.key_ = CONCAT(
                'vfs.fs.size[',
                fs.mount,
                ',used]'
            )

        JOIN LATERAL (

            SELECT value

            FROM history_uint

            WHERE itemid = iu.itemid

            ORDER BY clock DESC

            LIMIT 1

        ) used ON TRUE

        -- ====================================================
        -- PUSED
        -- ====================================================

        LEFT JOIN items ip

          ON ip.hostid = fs.hostid

         AND ip.key_ = CONCAT(
                'vfs.fs.size[',
                fs.mount,
                ',pused]'
            )

        LEFT JOIN LATERAL (

            SELECT value

            FROM history

            WHERE itemid = ip.itemid

            ORDER BY clock DESC

            LIMIT 1

        ) percent ON TRUE

        ORDER BY fs.mount
        """,

        (hostid,),
    )

    rows = cursor.fetchall()

    discos = []

    for row in rows:

        total_gb = (
            float(row["total_gb"])
            if row["total_gb"] is not None
            else 0
        )

        used_gb = (
            float(row["used_gb"])
            if row["used_gb"] is not None
            else 0
        )

        free_gb = (
            float(row["free_gb"])
            if row["free_gb"] is not None
            else max(total_gb - used_gb, 0)
        )

        uso = (
            float(row["percent"])
            if row["percent"] is not None
            else (
                (used_gb / total_gb) * 100
                if total_gb > 0
                else 0
            )
        )

        # Garante faixa válida
        uso = min(max(uso, 0), 100)

        discos.append(
            {
                # ============================================
                # CAMPOS PRINCIPAIS
                # ============================================

                "mount": row["mount"],

                "used_gb": round(used_gb, 2),

                "total_gb": round(total_gb, 2),

                "free_gb": round(free_gb, 2),

                "uso": round(uso, 2),

                # ============================================
                # CAMPOS EXTRAS PARA O FRONTEND
                # ============================================

                "free_percent": round(100 - uso, 2),

                "source": "windows",
            }
        )

    return discos

# ============================================================
# DISCOS LINUX
# ============================================================

def buscar_discos_linux(cursor, hostid):

    cursor.execute(
        """
        WITH filesystems AS (

            SELECT
                it.hostid,
                it.itemid,

                split_part(
                    split_part(
                        it.key_,
                        '[',
                        2
                    ),
                    ',',
                    1
                ) AS mount

            FROM items it

            WHERE it.hostid = %s
              AND it.key_ LIKE
                    'vfs.fs.dependent.size[%%,total]'

        )

        SELECT
            fs.mount,

            -- ================================================
            -- TOTAL
            -- ================================================

            ROUND(
                (
                    total.value::numeric
                    / 1024
                    / 1024
                    / 1024
                ),
                2
            ) AS total_gb,

            -- ================================================
            -- USADO
            -- ================================================

            ROUND(
                (
                    used.value::numeric
                    / 1024
                    / 1024
                    / 1024
                ),
                2
            ) AS used_gb,

            -- ================================================
            -- PERCENTUAL USADO
            -- ================================================

            ROUND(
                percent.value::numeric,
                2
            ) AS percent

        FROM filesystems fs

        -- ====================================================
        -- TOTAL
        -- ====================================================

        JOIN LATERAL (

            SELECT value

            FROM history_uint

            WHERE itemid = fs.itemid

            ORDER BY clock DESC

            LIMIT 1

        ) total ON TRUE

        -- ====================================================
        -- USED
        -- ====================================================

        JOIN items iu

          ON iu.hostid = fs.hostid

         AND iu.key_ = REPLACE(
                (
                    SELECT key_
                    FROM items
                    WHERE itemid = fs.itemid
                ),
                'total]',
                'used]'
            )

        JOIN LATERAL (

            SELECT value

            FROM history_uint

            WHERE itemid = iu.itemid

            ORDER BY clock DESC

            LIMIT 1

        ) used ON TRUE

        -- ====================================================
        -- PUSED
        -- ====================================================

        LEFT JOIN items ip

          ON ip.hostid = fs.hostid

         AND ip.key_ = REPLACE(
                (
                    SELECT key_
                    FROM items
                    WHERE itemid = fs.itemid
                ),
                'total]',
                'pused]'
            )

        LEFT JOIN LATERAL (

            SELECT value

            FROM history

            WHERE itemid = ip.itemid

            ORDER BY clock DESC

            LIMIT 1

        ) percent ON TRUE

        ORDER BY fs.mount
        """,

        (hostid,),
    )

    rows = cursor.fetchall()

    # ========================================================
    # RESULTADO PRINCIPAL
    # ========================================================

    if rows:

        discos = []

        for row in rows:

            total_gb = (
                float(row["total_gb"])
                if row["total_gb"] is not None
                else 0
            )

            used_gb = (
                float(row["used_gb"])
                if row["used_gb"] is not None
                else 0
            )

            # ------------------------------------------------
            # Espaço livre
            # ------------------------------------------------

            free_gb = max(
                total_gb - used_gb,
                0
            )

            # ------------------------------------------------
            # Percentual
            # ------------------------------------------------

            if row["percent"] is not None:

                uso = float(row["percent"])

            elif total_gb > 0:

                uso = (
                    used_gb
                    / total_gb
                ) * 100

            else:

                uso = 0

            # ------------------------------------------------
            # Limita entre 0 e 100
            # ------------------------------------------------

            uso = min(
                max(uso, 0),
                100
            )

            discos.append(
                {
                    # ========================================
                    # CAMPOS EXISTENTES
                    # ========================================

                    "mount": row["mount"],

                    "used_gb": round(
                        used_gb,
                        2
                    ),

                    "total_gb": round(
                        total_gb,
                        2
                    ),

                    "uso": round(
                        uso,
                        2
                    ),

                    # ========================================
                    # NOVOS CAMPOS
                    # ========================================

                    "free_gb": round(
                        free_gb,
                        2
                    ),

                    "free_percent": round(
                        100 - uso,
                        2
                    ),

                    "source": "linux",
                }
            )

        return discos

    # ========================================================
    # FALLBACK
    # ========================================================
    # Caso o host não possua os itens
    # vfs.fs.dependent.size
    # ========================================================

    cursor.execute(
        """
        SELECT

            split_part(
                split_part(
                    i.key_,
                    '[',
                    2
                ),
                ',',
                1
            ) AS mount,

            ROUND(
                h.value::numeric,
                2
            ) AS uso

        FROM items i

        JOIN LATERAL (

            SELECT value

            FROM history

            WHERE itemid = i.itemid

            ORDER BY clock DESC

            LIMIT 1

        ) h ON TRUE

        WHERE i.hostid = %s

          AND i.key_ LIKE
                'vfs.fs.size[%%,pused]'

        ORDER BY mount
        """,

        (hostid,),
    )

    rows = cursor.fetchall()

    # ========================================================
    # RETORNO DO FALLBACK
    # ========================================================

    discos = []

    for row in rows:

        uso = float(row["uso"])

        uso = min(
            max(uso, 0),
            100
        )

        discos.append(
            {
                "mount": row["mount"],

                # Não temos os valores absolutos
                # nesse fallback
                "used_gb": None,

                "total_gb": None,

                "free_gb": None,

                "uso": round(
                    uso,
                    2
                ),

                "free_percent": round(
                    100 - uso,
                    2
                ),

                "source": "linux_fallback",
            }
        )

    return discos
# ============================================================
# DISCOS
# ============================================================

def get_discos(cursor, hostid, os_type):

    # Normaliza o sistema operacional
    os_type = str(os_type or "").lower().strip()

    # ========================================================
    # WINDOWS
    # ========================================================

    if os_type == "windows":
        return buscar_discos_windows(
            cursor,
            hostid,
        )

    # ========================================================
    # LINUX
    # ========================================================

    if os_type == "linux":
        return buscar_discos_linux(
            cursor,
            hostid,
        )

    # ========================================================
    # FALLBACK
    # ========================================================
    # Se não conseguiu identificar o SO,
    # tenta Linux como padrão.
    # ========================================================

    return buscar_discos_linux(
        cursor,
        hostid,
    )

# ============================================================
# MEMÓRIA
# ============================================================

def get_memoria(cursor, hostid):

    # ========================================================
    # TOTAL
    # ========================================================

    cursor.execute(
        """
        SELECT hu.value
        FROM items it
        JOIN LATERAL (
            SELECT value
            FROM history_uint
            WHERE itemid = it.itemid
            ORDER BY clock DESC
            LIMIT 1
        ) hu ON TRUE
        WHERE it.hostid = %s
          AND it.key_ = 'vm.memory.size[total]'
        LIMIT 1
        """,
        (hostid,),
    )

    total_row = cursor.fetchone()

    if not total_row:
        return {
            "percent": 0,
            "used_gb": 0,
            "available_gb": 0,
            "total_gb": 0,
            "used_bytes": 0,
            "available_bytes": 0,
            "total_bytes": 0,
        }

    total = float(total_row["value"])

    # ========================================================
    # PERCENTUAL DE USO
    # ========================================================

    cursor.execute(
        """
        SELECT
            it.key_,
            h.value
        FROM items it
        JOIN LATERAL (
            SELECT value
            FROM history
            WHERE itemid = it.itemid
            ORDER BY clock DESC
            LIMIT 1
        ) h ON TRUE
        WHERE it.hostid = %s
          AND it.key_ IN (
                'vm.memory.utilization',
                'vm.memory.util'
          )
        ORDER BY
            CASE it.key_
                WHEN 'vm.memory.utilization' THEN 1
                WHEN 'vm.memory.util' THEN 2
                ELSE 3
            END
        LIMIT 1
        """,
        (hostid,),
    )

    percent_row = cursor.fetchone()

    # ========================================================
    # MEMÓRIA USADA
    # ========================================================

    cursor.execute(
        """
        SELECT hu.value
        FROM items it
        JOIN LATERAL (
            SELECT value
            FROM history_uint
            WHERE itemid = it.itemid
            ORDER BY clock DESC
            LIMIT 1
        ) hu ON TRUE
        WHERE it.hostid = %s
          AND it.key_ = 'vm.memory.size[used]'
        LIMIT 1
        """,
        (hostid,),
    )

    used_row = cursor.fetchone()

    # ========================================================
    # MEMÓRIA DISPONÍVEL
    # ========================================================

    cursor.execute(
        """
        SELECT hu.value
        FROM items it
        JOIN LATERAL (
            SELECT value
            FROM history_uint
            WHERE itemid = it.itemid
            ORDER BY clock DESC
            LIMIT 1
        ) hu ON TRUE
        WHERE it.hostid = %s
          AND it.key_ = 'vm.memory.size[available]'
        LIMIT 1
        """,
        (hostid,),
    )

    available_row = cursor.fetchone()

    # ========================================================
    # CALCULAR USED
    # ========================================================

    used = 0

    if used_row:
        used = float(used_row["value"])

    # ========================================================
    # CALCULAR AVAILABLE
    # ========================================================

    available = 0

    if available_row:
        available = float(available_row["value"])

    # ========================================================
    # FALLBACK
    #
    # Se não encontrou available, calcula:
    #
    # available = total - used
    # ========================================================

    if available <= 0 and used > 0:
        available = total - used

    # Evita valores negativos
    available = max(available, 0)

    # ========================================================
    # FALLBACK PARA USED
    #
    # Se não encontrou used, calcula:
    #
    # used = total - available
    # ========================================================

    if used <= 0 and available > 0:
        used = total - available

    used = max(used, 0)

    # ========================================================
    # PERCENTUAL
    # ========================================================

    percent = 0

    if percent_row:
        percent = float(percent_row["value"])

    elif total > 0:
        percent = (used / total) * 100

    # ========================================================
    # LIMITAR PERCENTUAL
    # ========================================================

    percent = min(max(percent, 0), 100)

    # ========================================================
    # RETORNO
    # ========================================================

    return {
        # Percentual utilizado
        "percent": round(percent, 2),

        # Valores em GB para o frontend
        "used_gb": round(
            used / 1024 / 1024 / 1024,
            2,
        ),

        "available_gb": round(
            available / 1024 / 1024 / 1024,
            2,
        ),

        "total_gb": round(
            total / 1024 / 1024 / 1024,
            2,
        ),

        # Valores originais em bytes
        "used_bytes": int(used),

        "available_bytes": int(available),

        "total_bytes": int(total),
    }

# ============================================================
# STATUS / PING / UPTIME
# ============================================================

def get_status_ping_uptime(cursor, hostid):

    cursor.execute(
        """
        SELECT
            h.status AS host_status,

            ping.value AS icmp_ping,

            latency.value AS latency_seconds,

            uptime.value AS uptime_seconds

        FROM hosts h

        --- ----------------------------------------------------
        --- ICMP PING
        --- ----------------------------------------------------

        LEFT JOIN items i_ping
          ON i_ping.hostid = h.hostid
         AND i_ping.key_ = 'icmpping'

        LEFT JOIN LATERAL (
            SELECT value
            FROM history_uint
            WHERE itemid = i_ping.itemid
            ORDER BY clock DESC
            LIMIT 1
        ) ping ON TRUE

        --- ----------------------------------------------------
        --- LATÊNCIA
        --- ----------------------------------------------------

        LEFT JOIN items i_latency
          ON i_latency.hostid = h.hostid
         AND i_latency.key_ = 'icmppingsec'

        LEFT JOIN LATERAL (
            SELECT value
            FROM history
            WHERE itemid = i_latency.itemid
            ORDER BY clock DESC
            LIMIT 1
        ) latency ON TRUE

        --- ----------------------------------------------------
        --- UPTIME
        --- ----------------------------------------------------

        LEFT JOIN items i_uptime
          ON i_uptime.hostid = h.hostid
         AND i_uptime.key_ = 'system.uptime'

        LEFT JOIN LATERAL (
            SELECT value
            FROM history_uint
            WHERE itemid = i_uptime.itemid
            ORDER BY clock DESC
            LIMIT 1
        ) uptime ON TRUE

        WHERE h.hostid = %s

        LIMIT 1
        """,
        (hostid,),
    )

    row = cursor.fetchone()

    # ========================================================
    # HOST NÃO ENCONTRADO
    # ========================================================

    if not row:
        return {
            "status": "UNKNOWN",
            "host_status": None,

            "icmp_ping": None,
            "ping_available": False,

            "latency_ms": None,

            "uptime_seconds": None,
            "uptime_days": None,
            "uptime_available": False,
        }

    # ========================================================
    # STATUS DO HOST NO ZABBIX
    # ========================================================

    host_enabled = (
        row["host_status"] == 0
    )

    # ========================================================
    # ICMP
    # ========================================================

    icmp_ping = row["icmp_ping"]

    ping_available = (
        icmp_ping is not None
    )

    # ========================================================
    # STATUS
    #
    # ICMP determina UP/DOWN.
    # UPTIME é apenas informação complementar.
    # ========================================================

    if not host_enabled:

        status = "DISABLED"

    elif icmp_ping is not None:

        status = (
            "UP"
            if float(icmp_ping) == 1
            else "DOWN"
        )

    else:

        status = "UNKNOWN"

    # ========================================================
    # LATÊNCIA
    # ========================================================

    latency = row["latency_seconds"]

    if latency is not None:

        latency_ms = round(
            float(latency) * 1000,
            2,
        )

    else:

        latency_ms = None

    # ========================================================
    # UPTIME
    # ========================================================

    uptime = row["uptime_seconds"]

    if uptime is not None:

        uptime_seconds = int(
            float(uptime)
        )

        uptime_days = round(
            uptime_seconds / 86400,
            2,
        )

    else:

        uptime_seconds = None
        uptime_days = None

    uptime_available = (
        uptime_seconds is not None
    )

    # ========================================================
    # RETORNO
    # ========================================================

    return {

        # ----------------------------------------------------
        # STATUS
        # ----------------------------------------------------

        "status": status,

        "host_status": (
            "ENABLED"
            if host_enabled
            else "DISABLED"
        ),

        # ----------------------------------------------------
        # PING
        # ----------------------------------------------------

        "icmp_ping": icmp_ping,

        "ping_available": ping_available,

        # ----------------------------------------------------
        # LATÊNCIA
        # ----------------------------------------------------

        "latency_ms": latency_ms,

        # ----------------------------------------------------
        # UPTIME
        # ----------------------------------------------------

        "uptime_seconds": uptime_seconds,

        "uptime_days": uptime_days,

        "uptime_available": uptime_available,
    }


# ============================================================
# STATUS DE TODOS OS HOSTS
# ============================================================

def get_status_ping_uptime_all(cursor):

    cursor.execute(
        """
        SELECT
            h.hostid,

            h.status AS host_status,

            ping.value AS icmp_ping,

            latency.value AS latency_seconds,

            uptime.value AS uptime_seconds

        FROM hosts h

        --- ----------------------------------------------------
        --- ICMP PING
        --- ----------------------------------------------------

        LEFT JOIN items i_ping
          ON i_ping.hostid = h.hostid
         AND i_ping.key_ = 'icmpping'

        LEFT JOIN LATERAL (
            SELECT value
            FROM history_uint
            WHERE itemid = i_ping.itemid
            ORDER BY clock DESC
            LIMIT 1
        ) ping ON TRUE

        --- ----------------------------------------------------
        --- LATÊNCIA
        --- ----------------------------------------------------

        LEFT JOIN items i_latency
          ON i_latency.hostid = h.hostid
         AND i_latency.key_ = 'icmppingsec'

        LEFT JOIN LATERAL (
            SELECT value
            FROM history
            WHERE itemid = i_latency.itemid
            ORDER BY clock DESC
            LIMIT 1
        ) latency ON TRUE

        --- ----------------------------------------------------
        --- UPTIME
        --- ----------------------------------------------------

        LEFT JOIN items i_uptime
          ON i_uptime.hostid = h.hostid
         AND i_uptime.key_ = 'system.uptime'

        LEFT JOIN LATERAL (
            SELECT value
            FROM history_uint
            WHERE itemid = i_uptime.itemid
            ORDER BY clock DESC
            LIMIT 1
        ) uptime ON TRUE

        ORDER BY h.host
        """
    )

    rows = cursor.fetchall()

    resultado = []

    for row in rows:

        # ====================================================
        # STATUS DO HOST
        # ====================================================

        host_enabled = (
            row["host_status"] == 0
        )

        # ====================================================
        # ICMP
        # ====================================================

        icmp_ping = row["icmp_ping"]

        ping_available = (
            icmp_ping is not None
        )

        # ====================================================
        # STATUS
        # ====================================================

        if not host_enabled:

            status = "DISABLED"

        elif icmp_ping is not None:

            status = (
                "UP"
                if float(icmp_ping) == 1
                else "DOWN"
            )

        else:

            status = "UNKNOWN"

        # ====================================================
        # LATÊNCIA
        # ====================================================

        latency = row["latency_seconds"]

        if latency is not None:

            latency_ms = round(
                float(latency) * 1000,
                2,
            )

        else:

            latency_ms = None

        # ====================================================
        # UPTIME
        # ====================================================

        uptime = row["uptime_seconds"]

        if uptime is not None:

            uptime_seconds = int(
                float(uptime)
            )

            uptime_days = round(
                uptime_seconds / 86400,
                2,
            )

        else:

            uptime_seconds = None
            uptime_days = None

        uptime_available = (
            uptime_seconds is not None
        )

        # ====================================================
        # RETORNO
        # ====================================================

        resultado.append(
            {
                # ------------------------------------------------
                # IDENTIFICAÇÃO
                # ------------------------------------------------

                "hostid": row["hostid"],

                # ------------------------------------------------
                # STATUS
                # ------------------------------------------------

                "status": status,

                "host_status": (
                    "ENABLED"
                    if host_enabled
                    else "DISABLED"
                ),

                # ------------------------------------------------
                # PING
                # ------------------------------------------------

                "icmp_ping": icmp_ping,

                "ping_available": ping_available,

                # ------------------------------------------------
                # LATÊNCIA
                # ------------------------------------------------

                "latency_ms": latency_ms,

                # ------------------------------------------------
                # UPTIME
                # ------------------------------------------------

                "uptime_seconds": uptime_seconds,

                "uptime_days": uptime_days,

                "uptime_available": uptime_available,
            }
        )

    return resultado

# ============================================================
# BUSCAR HOST POR ID
# ============================================================

def buscar_host_por_id_cursor(cursor, hostid):
    """
    Busca os dados básicos do host utilizando
    o cursor já aberto pela aplicação.

    Não abre nem fecha conexão PostgreSQL.

    Retorna:
        hostid
        nome
        ip
        porta_customizada
    """

    query = """
        SELECT
            h.hostid,
            h.host AS nome,
            i.ip

        FROM hosts h

        LEFT JOIN interface i
            ON h.hostid = i.hostid
           AND i.main = 1

        WHERE h.hostid = %s

        LIMIT 1
    """

    cursor.execute(
        query,
        (hostid,),
    )

    host = cursor.fetchone()

    # ========================================================
    # HOST NÃO ENCONTRADO
    # ========================================================

    if not host:
        return None

    # ========================================================
    # IP
    # ========================================================

    ip = host.get("ip")

    # ========================================================
    # PORTA CUSTOMIZADA
    # ========================================================

    host["porta_customizada"] = (
        gerar_porta_do_ip(ip)
        if ip
        else None
    )

    # ========================================================
    # RETORNO
    # ========================================================

    return host

# ============================================================
# MÉTRICAS COMPLETAS DO HOST
# ============================================================

def get_host_metrics(hostid):

    now = time.time()

    # ========================================================
    # CACHE LOCAL
    # ========================================================

    cached = HOST_METRICS_CACHE.get(hostid)

    if cached:

        cached_time, cached_data = cached

        if now - cached_time < CACHE_TTL:

            print(
                f"[LOCAL CACHE] HIT hostid={hostid}"
            )

            return cached_data

    print("=" * 80)
    print(f"[METRICS] INICIANDO hostid={hostid}")
    print("=" * 80)

    conn = conectar_postgres()

    print("[POSTGRES] conexão criada")

    cursor = conn.cursor(
        cursor_factory=RealDictCursor
    )

    print("[POSTGRES] cursor criado")

    try:

        # ====================================================
        # 1 - HOST
        # ====================================================

        print("[1/8] buscando host...")

        host_data = buscar_host_por_id_cursor(
            cursor,
            hostid,
        ) or {}

        print(
            f"[1/8] host_data = {host_data}"
        )

        ip = host_data.get("ip")

        porta_customizada = host_data.get(
            "porta_customizada"
        )

        # ====================================================
        # 2 - NOME
        # ====================================================

        print("[2/8] buscando nome...")

        nome = get_host_name(
            cursor,
            hostid,
        )

        print(
            f"[2/8] nome = {nome}"
        )

        # ====================================================
        # 3 - SO
        # ====================================================

        print("[3/8] detectando SO...")

        os_info = detectar_so(
            cursor,
            hostid,
        )

        print(
            f"[3/8] os_info = {os_info}"
        )

        os_type = os_info.get(
            "type",
            "unknown",
        )

        # ====================================================
        # 4 - STATUS
        # ====================================================

        print("[4/8] buscando status...")

        status_info = get_status_ping_uptime(
            cursor,
            hostid,
        )

        print(
            f"[4/8] status = {status_info}"
        )

        # ====================================================
        # 5 - CPU
        # ====================================================

        print("[5/8] buscando CPU...")

        cpu = get_cpu_usage(
            cursor,
            hostid,
            os_type,
        )

        print(
            f"[5/8] CPU = {cpu}"
        )

        # ====================================================
        # 6 - MEMÓRIA
        # ====================================================

        print("[6/8] buscando memória...")

        memoria = get_memoria(
            cursor,
            hostid,
        )

        print(
            f"[6/8] memória = {memoria}"
        )

        # ====================================================
        # 7 - DISCOS
        # ====================================================

        print("[7/8] buscando discos...")

        discos = get_discos(
            cursor,
            hostid,
            os_type,
        )

        print(
            f"[7/8] discos = {discos}"
        )

        # ====================================================
        # 8 - SERVIÇOS
        # ====================================================

        print("[8/8] buscando serviços...")

        services = get_active_services(
            cursor,
            hostid,
        )

        print(
            f"[8/8] services = {services}"
        )

        # ====================================================
        # RESULTADO
        # ====================================================

        resultado = {

            "hostid": hostid,

            "nome": nome,

            "ip": ip,

            "porta_customizada":
                porta_customizada,

            # STATUS
            "status":
                status_info.get("status"),

            "host_status":
                status_info.get("host_status"),

            "icmp_ping":
                status_info.get("icmp_ping"),

            "latency_ms":
                status_info.get("latency_ms"),

            "uptime_seconds":
                status_info.get(
                    "uptime_seconds"
                ),

            # MÉTRICAS
            "cpu": cpu,

            "memoria": memoria,

            "discos": discos,

            # OS
            "os":
                os_info.get("name")
                or os_type.upper(),

            "os_type":
                os_type,

            # SERVIÇOS
            "services": services,
        }

        print("=" * 80)
        print(
            f"[METRICS] RESULTADO FINAL hostid={hostid}"
        )
        print(resultado)
        print("=" * 80)

        # ====================================================
        # CACHE LOCAL
        # ====================================================

        HOST_METRICS_CACHE[hostid] = (
            now,
            resultado,
        )

        return resultado

    except Exception as e:

        print("=" * 80)
        print(
            f"[METRICS] ERRO hostid={hostid}"
        )
        print(
            f"[METRICS] {type(e).__name__}: {e}"
        )
        print("=" * 80)

        import traceback
        traceback.print_exc()

        raise

    finally:

        cursor.close()
        conn.close()

        print(
            f"[POSTGRES] conexão fechada hostid={hostid}"
        )
# ============================================================
# INCIDENTES ATIVOS
# ============================================================

REDIS_KEY_INCIDENTES = (
    "incidentes:ativos:hoje"
)

REDIS_TTL = 2


def buscar_incidentes_ativos_do_dia(
    conn,
    redis_client=None,
):

    if redis_client:

        cache = redis_client.get(
            REDIS_KEY_INCIDENTES
        )

        if cache:

            if isinstance(cache, bytes):

                cache = cache.decode(
                    "utf-8"
                )

            return json.loads(cache)

    cursor = conn.cursor(
        cursor_factory=RealDictCursor
    )

    try:

        cursor.execute(
            """
            SELECT

                p.eventid,

                to_timestamp(
                    MAX(p.clock)
                ) AS hora_inicio,

                MAX(h.host) AS host,

                MAX(t.description)
                    AS incidente,

                MAX(t.priority)
                    AS severidade,

                ROUND(
                    EXTRACT(
                        EPOCH FROM NOW()
                    )
                    - MAX(p.clock)
                ) AS duracao_segundos

            FROM problem p

            JOIN events e
              ON e.eventid = p.eventid

            JOIN triggers t
              ON t.triggerid = e.objectid

            JOIN functions f
              ON f.triggerid = t.triggerid

            JOIN items i
              ON i.itemid = f.itemid

            JOIN hosts h
              ON h.hostid = i.hostid

            WHERE p.r_eventid IS NULL

              AND p.clock >= EXTRACT(
                    EPOCH FROM CURRENT_DATE
                  )

            GROUP BY p.eventid

            ORDER BY hora_inicio DESC
            """
        )

        resultados = cursor.fetchall()

    finally:

        cursor.close()

    for row in resultados:

        if row.get("hora_inicio"):

            row["hora_inicio"] = (
                row["hora_inicio"].isoformat()
                if isinstance(
                    row["hora_inicio"],
                    datetime,
                )
                else str(
                    row["hora_inicio"]
                )
            )

        duracao = row.get(
            "duracao_segundos"
        )

        if duracao is not None:

            total = int(
                float(duracao)
            )

            row["duracao"] = (
                f"{total // 3600:02}:"
                f"{(total % 3600) // 60:02}:"
                f"{total % 60:02}"
            )

            row["duracao_segundos"] = (
                total
            )

    if redis_client:

        redis_client.setex(
            REDIS_KEY_INCIDENTES,
            REDIS_TTL,
            json.dumps(
                resultados,
                default=str,
            ),
        )

    return resultados


# ============================================================
# TOTAL DE HOSTS
# ============================================================

def get_hosts_totais(conn):

    cursor = conn.cursor(
        cursor_factory=RealDictCursor
    )

    try:

        cursor.execute(
            """
            SELECT

                COUNT(*) FILTER (
                    WHERE status = 0
                ) AS online,

                COUNT(*) FILTER (
                    WHERE status = 1
                ) AS offline,

                COUNT(*) FILTER (
                    WHERE status = 3
                ) AS sem_acesso,

                COUNT(*) FILTER (
                    WHERE status = 5
                ) AS manutencao

            FROM hosts
            """
        )

        resultado = cursor.fetchone()

    finally:

        cursor.close()

    return {

        "online": int(
            resultado["online"] or 0
        ),

        "offline": int(
            resultado["offline"] or 0
        ),

        "sem_acesso": int(
            resultado["sem_acesso"] or 0
        ),

        "manutencao": int(
            resultado["manutencao"] or 0
        ),
    }


# ============================================================
# PROBLEMAS NAS ÚLTIMAS 24 HORAS
# ============================================================

def get_problemas_24h(conn):

    cursor = conn.cursor(
        cursor_factory=RealDictCursor
    )

    try:

        cursor.execute(
            """
            SELECT

                t.description AS problema,

                COUNT(e.eventid)
                    AS total_ocorrencias,

                ROUND(
                    (
                        COUNT(e.eventid)::numeric
                        /
                        NULLIF(
                            SUM(
                                COUNT(e.eventid)
                            ) OVER (),
                            0
                        )
                    ) * 100,
                    2
                ) AS porcentagem

            FROM events e

            JOIN triggers t
              ON e.objectid = t.triggerid

            WHERE e.source = 0

              AND e.object = 0

              AND e.value = 1

              AND e.clock >= EXTRACT(
                    EPOCH FROM (
                        NOW()
                        - INTERVAL '24 hours'
                    )
                  )

            GROUP BY t.description

            ORDER BY total_ocorrencias DESC

            LIMIT 10
            """
        )

        resultados = cursor.fetchall()

    finally:

        cursor.close()

    return [

        {
            "problema":
                row["problema"],

            "total_ocorrencias":
                int(
                    row["total_ocorrencias"]
                ),

            "porcentagem":
                float(
                    row["porcentagem"]
                    or 0
                ),
        }

        for row in resultados
    ]


# ============================================================
# PROBLEMAS 24H COM REDIS
# ============================================================

def get_problemas_24h_cache(conn):

    cache_key = (
        "dashboard:problemas_24h"
    )

    if redis_client:

        cached_data = redis_client.get(
            cache_key
        )

        if cached_data:

            if isinstance(
                cached_data,
                bytes,
            ):

                cached_data = (
                    cached_data.decode(
                        "utf-8"
                    )
                )

            return json.loads(
                cached_data
            )

    dados = get_problemas_24h(
        conn
    )

    if redis_client:

        redis_client.setex(
            cache_key,
            75,
            json.dumps(dados),
        )

    return dados


# ============================================================
# RELATÓRIO HOST INTELIGENTE
# ============================================================

def get_relatorio_host_inteligente(
    hostid,
    inicio,
    fim,
    agrupamento="15min",
):

    conn = conectar_postgres()

    cursor = conn.cursor(
        cursor_factory=RealDictCursor
    )

    try:

        # ====================================================
        # AGRUPAMENTO
        # ====================================================

        def detectar_agrupamento(
            inicio,
            fim,
        ):

            fmt = "%Y-%m-%d %H:%M:%S"

            dt_inicio = datetime.strptime(
                inicio,
                fmt,
            )

            dt_fim = datetime.strptime(
                fim,
                fmt,
            )

            diff = (
                dt_fim - dt_inicio
            ).total_seconds()

            if diff <= 7200:

                return "15min"

            elif diff <= 172800:

                return "hora"

            return "dia"

        if agrupamento == "auto":

            agrupamento = (
                detectar_agrupamento(
                    inicio,
                    fim,
                )
            )

        # ====================================================
        # CPU WINDOWS
        # ====================================================

        CPU_WIN_KEY = (
            r"perf_counter[\Processor Information(_Total)\% Processor Utility]"
        )

        cursor.execute(
            """
            SELECT itemid

            FROM items

            WHERE hostid = %s

              AND key_ = %s

            LIMIT 1
            """,
            (
                hostid,
                CPU_WIN_KEY,
            ),
        )

        cpu_item = cursor.fetchone()

        # ====================================================
        # CPU LINUX EXATA
        # ====================================================

        if not cpu_item:

            cursor.execute(
                """
                SELECT itemid

                FROM items

                WHERE hostid = %s

                  AND key_ =
                    'system.cpu.util[all,,avg1]'

                LIMIT 1
                """,
                (hostid,),
            )

            cpu_item = cursor.fetchone()

        # ====================================================
        # CPU LINUX FALLBACK
        # ====================================================

        if not cpu_item:

            cursor.execute(
                """
                SELECT itemid

                FROM items

                WHERE hostid = %s

                  AND key_ LIKE
                    'system.cpu.util%%'

                LIMIT 1
                """,
                (hostid,),
            )

            cpu_item = cursor.fetchone()

        # ====================================================
        # MEMÓRIA
        # ====================================================

        cursor.execute(
            """
            SELECT itemid

            FROM items

            WHERE hostid = %s

              AND key_ IN (
                    'vm.memory.utilization',
                    'vm.memory.size[pused]'
              )

            LIMIT 1
            """,
            (hostid,),
        )

        mem_item = cursor.fetchone()

        # ====================================================
        # PING
        # ====================================================

        cursor.execute(
            """
            SELECT itemid

            FROM items

            WHERE hostid = %s

              AND key_ = 'icmpping'

            LIMIT 1
            """,
            (hostid,),
        )

        ping_item = cursor.fetchone()

        # ====================================================
        # AGENT PING FALLBACK
        # ====================================================

        if not ping_item:

            cursor.execute(
                """
                SELECT itemid

                FROM items

                WHERE hostid = %s

                  AND key_ = 'agent.ping'

                LIMIT 1
                """,
                (hostid,),
            )

            ping_item = cursor.fetchone()

        # ====================================================
        # SÉRIE DINÂMICA
        # ====================================================

        def serie_dinamica(
            itemid,
            is_uint=False,
        ):

            if not itemid:

                return []

            # ==============================================
            # 15 MINUTOS
            # ==============================================

            if agrupamento == "15min":

                tabela = (
                    "history_uint"
                    if is_uint
                    else "history"
                )

                sql = f"""
                    SELECT

                        to_timestamp(
                            FLOOR(clock / 900)
                            * 900
                        ) AS data,

                        ROUND(
                            AVG(value)::numeric,
                            2
                        ) AS avg,

                        ROUND(
                            MIN(value)::numeric,
                            2
                        ) AS min,

                        ROUND(
                            MAX(value)::numeric,
                            2
                        ) AS max

                    FROM {tabela}

                    WHERE itemid = %s

                      AND clock BETWEEN
                            EXTRACT(
                                EPOCH FROM
                                %s::timestamp
                            )
                            AND
                            EXTRACT(
                                EPOCH FROM
                                %s::timestamp
                            )

                    GROUP BY
                        FLOOR(clock / 900)

                    ORDER BY data
                """

                cursor.execute(
                    sql,
                    (
                        itemid,
                        inicio,
                        fim,
                    ),
                )

                rows = cursor.fetchall()

                return serializar(
                    rows
                )

            # ==============================================
            # HORA
            # ==============================================

            tabela = (
                "trends_uint"
                if is_uint
                else "trends"
            )

            if agrupamento == "hora":

                trunc_expr = (
                    "date_trunc("
                    "'hour', "
                    "to_timestamp(t.clock)"
                    ")"
                )

            else:

                trunc_expr = (
                    "date_trunc("
                    "'day', "
                    "to_timestamp(t.clock)"
                    ")"
                )

            sql = f"""
                SELECT

                    {trunc_expr}
                        AS data,

                    ROUND(
                        MIN(
                            t.value_min
                        )::numeric,
                        4
                    ) AS min,

                    ROUND(
                        AVG(
                            t.value_avg
                        )::numeric,
                        4
                    ) AS avg,

                    ROUND(
                        MAX(
                            t.value_max
                        )::numeric,
                        4
                    ) AS max,

                    ROUND(
                        MAX(
                            t.value_avg
                        )::numeric,
                        4
                    ) AS last_value_avg,

                    ROUND(
                        MAX(
                            t.value_max
                        )::numeric,
                        4
                    ) AS last_value_max

                FROM {tabela} t

                WHERE t.itemid = %s

                  AND t.clock >= EXTRACT(
                        EPOCH FROM
                        %s::timestamp
                      )

                  AND t.clock < EXTRACT(
                        EPOCH FROM
                        %s::timestamp
                      )

                GROUP BY
                    {trunc_expr}

                ORDER BY data
            """

            cursor.execute(
                sql,
                (
                    itemid,
                    inicio,
                    fim,
                ),
            )

            rows = cursor.fetchall()

            return serializar(
                rows
            )

        # ====================================================
        # SÉRIE APRIMORADA
        # ====================================================

        def serie_aprimorada(
            itemid,
            is_uint=False,
        ):

            return serie_dinamica(
                itemid,
                is_uint=is_uint,
            )

        # ====================================================
        # DISCOS
        # ====================================================

        cursor.execute(
            """
            SELECT
                itemid,
                key_

            FROM items

            WHERE hostid = %s

              AND key_ LIKE
                    'vfs.fs.size%%pused%%'
            """,
            (hostid,),
        )

        discos_items = cursor.fetchall()

        discos = {}

        for item in discos_items:

            try:

                key = item["key_"]

                if "[" not in key:

                    continue

                disco_nome = (
                    key
                    .split("[", 1)[1]
                    .split(",", 1)[0]
                )

                if (
                    "{#FSNAME}"
                    in disco_nome
                ):

                    continue

                discos[disco_nome] = (
                    serie_dinamica(
                        item["itemid"]
                    )
                )

            except Exception:

                continue

        # ====================================================
        # RETORNO
        # ====================================================

        return {

            "agrupamento":
                agrupamento,

            "cpu":
                (
                    serie_aprimorada(
                        cpu_item["itemid"]
                    )
                    if cpu_item
                    else []
                ),

            "memoria":
                (
                    serie_aprimorada(
                        mem_item["itemid"]
                    )
                    if mem_item
                    else []
                ),

            "disponibilidade":
                (
                    serie_dinamica(
                        ping_item["itemid"],
                        is_uint=True,
                    )
                    if ping_item
                    else []
                ),

            "discos":
                discos,
        }

    finally:

        cursor.close()

        conn.close()


# ============================================================
# RELATÓRIO POR PERÍODO
# ============================================================

def get_relatorio_host_periodo(
    hostid,
    inicio,
    fim,
):

    conn = conectar_postgres()

    cursor = conn.cursor(
        cursor_factory=RealDictCursor
    )

    try:

        # ====================================================
        # CPU
        # ====================================================

        cursor.execute(
            """
            SELECT itemid

            FROM items

            WHERE hostid = %s

              AND (
                    key_ LIKE '%%Processor%%'
                    OR key_ LIKE
                        'system.cpu%%'
              )

            LIMIT 1
            """,
            (hostid,),
        )

        cpu_item = cursor.fetchone()

        # ====================================================
        # MEMÓRIA
        # ====================================================

        cursor.execute(
            """
            SELECT itemid

            FROM items

            WHERE hostid = %s

              AND key_ IN (
                    'vm.memory.size[pused]',
                    'vm.memory.utilization'
              )

            LIMIT 1
            """,
            (hostid,),
        )

        mem_item = cursor.fetchone()

        # ====================================================
        # PING
        # ====================================================

        cursor.execute(
            """
            SELECT itemid

            FROM items

            WHERE hostid = %s

              AND key_ = 'icmpping'

            LIMIT 1
            """,
            (hostid,),
        )

        ping_item = cursor.fetchone()

        # ====================================================
        # RESUMO
        # ====================================================

        def resumo(
            itemid,
            tabela="history",
        ):

            if not itemid:

                return None

            sql = f"""
                SELECT

                    ROUND(
                        MIN(value)::numeric,
                        2
                    ) AS min,

                    ROUND(
                        AVG(value)::numeric,
                        2
                    ) AS avg,

                    ROUND(
                        MAX(value)::numeric,
                        2
                    ) AS max

                FROM {tabela}

                WHERE itemid = %s

                  AND clock BETWEEN
                        EXTRACT(
                            EPOCH FROM
                            %s::timestamp
                        )
                        AND
                        EXTRACT(
                            EPOCH FROM
                            %s::timestamp
                        )
            """

            cursor.execute(
                sql,
                (
                    itemid,
                    inicio,
                    fim,
                ),
            )

            row = cursor.fetchone()

            if not row:

                return None

            return {
                "min": (
                    float(row["min"])
                    if row["min"] is not None
                    else None
                ),

                "avg": (
                    float(row["avg"])
                    if row["avg"] is not None
                    else None
                ),

                "max": (
                    float(row["max"])
                    if row["max"] is not None
                    else None
                ),
            }

        # ====================================================
        # RETORNO
        # ====================================================

        return {

            "cpu":
                (
                    resumo(
                        cpu_item["itemid"]
                    )
                    if cpu_item
                    else None
                ),

            "memoria":
                (
                    resumo(
                        mem_item["itemid"]
                    )
                    if mem_item
                    else None
                ),

            "disponibilidade":
                (
                    resumo(
                        ping_item["itemid"],
                        "history_uint",
                    )
                    if ping_item
                    else None
                ),
        }

    finally:

        cursor.close()

        conn.close()


# ============================================================
# GRÁFICO DE HOST
# ============================================================

def get_grafico_host(
    hostid,
    item_key,
    inicio,
    fim,
):

    conn = conectar_postgres()

    cursor = conn.cursor(
        cursor_factory=RealDictCursor
    )

    try:

        cursor.execute(
            """
            SELECT

                itemid,
                value_type

            FROM items

            WHERE hostid = %s

              AND key_ = %s

            LIMIT 1
            """,
            (
                hostid,
                item_key,
            ),
        )

        item = cursor.fetchone()

        if not item:

            return []

        value_type = int(
            item["value_type"]
        )

        # Zabbix:
        #
        # 0 = float
        # 3 = unsigned integer

        if value_type == 3:

            tabela = "history_uint"

        else:

            tabela = "history"

        cursor.execute(
            f"""
            SELECT

                to_timestamp(clock)
                    AS data,

                value

            FROM {tabela}

            WHERE itemid = %s

              AND clock BETWEEN
                    EXTRACT(
                        EPOCH FROM
                        %s::timestamp
                    )
                    AND
                    EXTRACT(
                        EPOCH FROM
                        %s::timestamp
                    )

            ORDER BY clock
            """,
            (
                item["itemid"],
                inicio,
                fim,
            ),
        )

        return serializar(
            cursor.fetchall()
        )

    finally:

        cursor.close()

        conn.close()


# ============================================================
# GRUPOS
# ============================================================

def get_grupos():

    conn = conectar_postgres()

    cursor = conn.cursor(
        cursor_factory=RealDictCursor
    )

    try:

        cursor.execute(
            """
            SELECT

                groupid,
                name

            FROM hstgrp

            ORDER BY name
            """
        )

        return cursor.fetchall()

    finally:

        cursor.close()

        conn.close()


# ============================================================
# HOSTS POR GRUPO
# ============================================================

def get_hosts_por_grupo(groupid):

    conn = conectar_postgres()

    cursor = conn.cursor(
        cursor_factory=RealDictCursor
    )

    try:

        cursor.execute(
            """
            SELECT

                h.hostid,
                h.host

            FROM hosts h

            JOIN hosts_groups hg
              ON h.hostid = hg.hostid

            WHERE hg.groupid = %s

              AND h.status = 0

            ORDER BY h.host
            """,
            (groupid,),
        )

        return cursor.fetchall()

    finally:

        cursor.close()

        conn.close()


# ============================================================
# GERA PORTA CUSTOMIZADA
# ============================================================

def gerar_porta_do_ip(ip):

    try:

        if not ip:

            return None

        partes = ip.split(".")

        if len(partes) != 4:

            return None

        terceiro = partes[2]

        quarto = int(
            partes[3]
        )

        if len(terceiro) == 1:

            terceiro_fmt = (
                f"{terceiro}00"
            )

        elif len(terceiro) == 2:

            terceiro_fmt = (
                f"{terceiro}0"
            )

        else:

            terceiro_fmt = terceiro

        quarto_fmt = (
            f"{quarto:02d}"
        )

        return (
            terceiro_fmt
            + quarto_fmt
        )

    except Exception:

        return None


# ============================================================
# HOSTS COM IP
# ============================================================

def buscar_hosts_com_ip():

    conn = conectar_postgres()

    cursor = conn.cursor(
        cursor_factory=RealDictCursor
    )

    try:

        query = """
            SELECT

                g.groupid,

                g.name AS nome_grupo,

                h.hostid,

                h.host AS nome_host,

                i.ip,

                i.port

            FROM hstgrp g

            JOIN hosts_groups hg
              ON g.groupid = hg.groupid

            JOIN hosts h
              ON hg.hostid = h.hostid

            LEFT JOIN interface i
              ON h.hostid = i.hostid
             AND i.main = 1

            WHERE h.status = 0

              AND h.flags = 0

            ORDER BY
                g.name,
                h.host
        """

        cursor.execute(query)

        dados = cursor.fetchall()

        for host in dados:

            ip = host.get("ip")

            hostid = host.get(
                "hostid"
            )

            if ip:

                host[
                    "porta_customizada"
                ] = gerar_porta_do_ip(
                    ip
                )

            else:

                host[
                    "porta_customizada"
                ] = None

            try:

                host["os"] = detectar_so(
                    cursor,
                    hostid,
                )

            except Exception:

                host["os"] = {
                    "type": "unknown",
                    "name": None,
                }

        return dados

    finally:

        cursor.close()

        conn.close()


# ============================================================
# BUSCAR IP DO HOST
# ============================================================

def buscar_ip_do_host(
    cursor,
    hostid,
):

    cursor.execute(
        """
        SELECT ip

        FROM interface

        WHERE hostid = %s

          AND main = 1

        LIMIT 1
        """,
        (hostid,),
    )

    row = cursor.fetchone()

    if row and row.get("ip"):

        return row["ip"]

    return None


# ============================================================
# BUSCAR HOST POR ID
# ============================================================

def buscar_host_por_id_cursor(
    cursor,
    hostid,
):

    cursor.execute(
        """
        SELECT

            h.hostid,

            h.host AS nome,

            i.ip

        FROM hosts h

        LEFT JOIN interface i

          ON h.hostid = i.hostid

         AND i.main = 1

        WHERE h.hostid = %s

        LIMIT 1
        """,
        (hostid,),
    )

    host = cursor.fetchone()

    if host:

        ip = host.get("ip")

        host[
            "porta_customizada"
        ] = (
            gerar_porta_do_ip(ip)
            if ip
            else None
        )

    return host


def buscar_host_por_id(hostid):

    conn = conectar_postgres()

    cursor = conn.cursor(
        cursor_factory=RealDictCursor
    )

    try:

        return buscar_host_por_id_cursor(
            cursor,
            hostid,
        )

    finally:

        cursor.close()

        conn.close()


# ============================================================
# TESTE DE CONEXÃO
# ============================================================

def testar_conexao():

    conn = None

    try:

        conn = conectar_postgres()

        cursor = conn.cursor()

        cursor.execute(
            "SELECT version()"
        )

        version = cursor.fetchone()[0]

        cursor.close()

        print(
            "[POSTGRES] Conexão OK"
        )

        print(
            f"[POSTGRES] {version}"
        )

        return True

    except Exception as e:

        print(
            f"[POSTGRES] Falha: {e}"
        )

        return False

    finally:

        if conn:

            conn.close()


# ============================================================
# EXECUÇÃO DIRETA
# ============================================================

if __name__ == "__main__":

    testar_conexao()