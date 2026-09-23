# ============================================================
# IMPORTS
# ============================================================

import json
import os
import traceback
from io import BytesIO

import requests

from dotenv import load_dotenv

from flask import (
    Flask,
    abort,
    jsonify,
    redirect,
    render_template,
    request,
    Response,
    send_from_directory,
    session,
    url_for,
)

from PIL import Image, ImageDraw, ImageFont

from werkzeug.middleware.proxy_fix import ProxyFix


# ============================================================
# LOAD ENV
# ============================================================

load_dotenv()


# ============================================================
# AUTH MICROSOFT
# ============================================================

from auth_microsoft import (
    build_auth_url,
    build_msal_app,
    SCOPE,
)


# ============================================================
# CONSULTA / ZABBIX
# ============================================================

from consulta import (
    coletar_dados,
    get_grupos_com_hosts,
    get_hosts_por_grupo,
    get_grupos,
    buscar_host_por_id,
    get_relatorio_host_inteligente,
    get_host_metrics,
    buscar_incidentes_ativos_do_dia,
    get_hosts_totais,
    get_problemas_24h_cache,
    get_relatorio_host_periodo,
    get_grafico_host,
    buscar_hosts_com_ip,
    conectar_postgres,
)


# ============================================================
# BANCO / SESSÃO / AUDITORIA
# ============================================================

from data import (
    bdmonitoramento,
    update_user_theme,
    funcmonitor,
    buscar_usuario_por_oid,
    criar_sessao_portal,
    registrar_logout,
    salvar_auditoria_login,
    atualizar_atividade_sessao,
)


# ============================================================
# MIDDLEWARE
# ============================================================

from middleware import middleware_autenticacao


# ============================================================
# ROLES
# ============================================================

from services.role_service import is_sustentacao


# ============================================================
# GUACAMOLE
# ============================================================

from guacamole.service import (
    get_token,
    get_connections,
    GUAC_URL,
    conectar_ou_criar,
    get_hosts,
    encode_guac_id,
    gerar_link_conexao,
)


# ============================================================
# REDIS
# ============================================================

from cache import redis_client

# ============================================================
# JSON
# ============================================================

from utils import normalize_for_json

# ============================================================
# CONFIGURAÇÃO
# ============================================================

APP_ENV = os.getenv("APP_ENV", "development").lower()

FLASK_SECRET = os.getenv(
    "FLASK_SECRET",
    "change-this-secret"
)

IP_HOST = os.getenv("IPHOST")

API_CLIENTES = os.getenv("HOSTCLIENT", "").rstrip("/")


# ============================================================
# FLASK APP
# ============================================================

app = Flask(
    __name__,
    static_folder="static",
    static_url_path="/static",
)


# ============================================================
# CONFIGURAÇÕES FLASK
# ============================================================

app.secret_key = FLASK_SECRET

app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=(
        os.getenv("SESSION_COOKIE_SECURE", "false").lower() == "true"
    ),
    PREFERRED_URL_SCHEME=os.getenv(
        "PREFERRED_URL_SCHEME",
        "http"
    ),
)


# ============================================================
# PROXY FIX
# ============================================================

# Necessário quando Flask está atrás de Nginx / Proxy.
#
# X-Forwarded-For
# X-Forwarded-Proto
# X-Forwarded-Host

app.wsgi_app = ProxyFix(
    app.wsgi_app,
    x_for=1,
    x_proto=1,
    x_host=1,
)


# ============================================================
# MIDDLEWARE DE AUTENTICAÇÃO
# ============================================================

middleware_autenticacao(app)


# ============================================================
# ROTAS LIVRES
# ============================================================

ROTAS_LIVRES = {
    "login",
    "login_microsoft",
    "auth_callback",
    "static",
    "static_files",
}


# ============================================================
# BEFORE REQUEST
# ============================================================

@app.before_request
def require_login():
    """
    Protege as rotas da aplicação.

    Rotas de autenticação e arquivos estáticos permanecem livres.
    """

    endpoint = request.endpoint

    if endpoint in ROTAS_LIVRES:
        return None

    if not endpoint:
        return None

    if "user" not in session:
        return redirect(url_for("login"))

    return None


# ============================================================
# AFTER REQUEST
# ============================================================

@app.after_request
def add_no_cache_headers(response):
    """
    Evita cache de páginas e APIs autenticadas.

    Isso é especialmente importante para:
    - logout
    - dashboard
    - informações de usuários
    - dados de monitoramento
    """

    response.headers["Cache-Control"] = (
        "no-store, no-cache, must-revalidate, private"
    )

    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"

    return response


# ============================================================
# STATIC
# ============================================================

@app.route("/static/<path:filename>")
def static_files(filename):
    return send_from_directory(
        app.static_folder,
        filename
    )


# ============================================================
# LOGIN MICROSOFT ENTRA ID
# ============================================================

@app.route("/login/microsoft")
def login_microsoft():
    """
    Redireciona o usuário para o Microsoft Entra ID.
    """

    return redirect(build_auth_url())


# ============================================================
# CALLBACK MICROSOFT
# ============================================================

@app.route("/auth/callback")
def auth_callback():
    """
    Processa o retorno do Microsoft Entra ID.
    """

    if "code" not in request.args:
        return (
            "Erro: código de autorização não retornado.",
            400
        )

    code = request.args.get("code")

    try:

        msal_app = build_msal_app()

        result = msal_app.acquire_token_by_authorization_code(
            code,
            scopes=SCOPE,
            redirect_uri=os.getenv(
                "AZURE_REDIRECT_URI"
            ),
        )

        if "error" in result:
            print(
                "ERRO MSAL:",
                result
            )

            return (
                jsonify({
                    "erro": "Falha na autenticação Microsoft.",
                    "detalhes": result,
                }),
                400,
            )

        access_token = result.get("access_token")

        if not access_token:
            return (
                jsonify({
                    "erro": "Access token não retornado."
                }),
                400,
            )

        # ====================================================
        # SERVIÇO AZURE
        # ====================================================

        from azure_service import AzureService

        azure = AzureService(access_token)

        # ====================================================
        # PERFIL
        # ====================================================

        perfil = azure.get_user_profile()

        if not perfil:
            return (
                jsonify({
                    "erro": "Não foi possível obter o perfil."
                }),
                400,
            )

        # ====================================================
        # GRUPOS
        # ====================================================

        grupos = azure.get_user_groups() or []

        # ====================================================
        # SIGN-IN INFO
        # ====================================================

        signin_info = azure.get_last_signin_info(
            perfil["oid"]
        )

        # ====================================================
        # USER
        # ====================================================

        user = {
            "name": perfil.get("nome"),
            "email": perfil.get("email"),
            "job_title": perfil.get("cargo"),
            "department": perfil.get("departamento"),
            "azure_oid": perfil.get("oid"),
            "groups": grupos,
            "signin_info": signin_info,
        }

        # ====================================================
        # SESSÃO
        # ====================================================

        session.permanent = True

        session["user"] = {
            "name": user["name"],
            "email": user["email"],
            "job": user["job_title"],
            "oid": user["azure_oid"],
        }

        # ----------------------------------------------------
        # IMPORTANTE
        # ----------------------------------------------------
        #
        # Evitamos armazenar access_token na sessão Flask.
        #
        # Se a aplicação usa sessão baseada em cookie,
        # armazenar o token aqui pode expô-lo ao navegador.
        #
        # Caso outras rotas precisem do token Microsoft,
        # recomendamos implementar armazenamento server-side.
        #
        # session["access_token"] = access_token
        #
        # ----------------------------------------------------

        # ====================================================
        # BANCO
        # ====================================================

        conn = None

        try:

            conn = bdmonitoramento()

            if conn:

                # --------------------------------------------
                # CRIA / ATUALIZA USUÁRIO
                # --------------------------------------------

                funcmonitor(
                    conn,
                    user
                )

                # --------------------------------------------
                # BUSCA USUÁRIO
                # --------------------------------------------

                db_user = buscar_usuario_por_oid(
                    conn,
                    user["azure_oid"]
                )

                if db_user:

                    # ----------------------------------------
                    # CRIA SESSÃO
                    # ----------------------------------------

                    session_id, session_token = (
                        criar_sessao_portal(
                            conn,
                            db_user["id"],
                            request
                        )
                    )

                    session["session_id"] = session_id
                    session["session_token"] = session_token
                    session["user_id"] = db_user["id"]

                    # ----------------------------------------
                    # AUDITORIA
                    # ----------------------------------------

                    if signin_info:

                        localizacao = (
                            signin_info.get(
                                "localizacao",
                                {}
                            )
                            or {}
                        )

                        salvar_auditoria_login(
                            conn=conn,
                            user_id=db_user["id"],
                            ip=signin_info.get(
                                "ip_login"
                            ),
                            sistema=signin_info.get(
                                "sistema_operacional"
                            ),
                            device_id=signin_info.get(
                                "device_id"
                            ),
                            cidade=localizacao.get(
                                "cidade"
                            ),
                            pais=localizacao.get(
                                "pais"
                            ),
                        )

        finally:

            if conn:
                conn.close()

        print(
            "LOGIN:",
            session["user"].get("email")
        )

        return redirect(
            url_for("index")
        )

    except Exception as exc:

        traceback.print_exc()

        return (
            jsonify({
                "erro": "Erro interno durante autenticação.",
                "detalhes": str(exc),
            }),
            500,
        )


# ============================================================
# LOGIN PRINCIPAL
# ============================================================

@app.route("/", methods=["GET", "POST"])
def login():
    """
    Página inicial / autenticação.
    """

    # --------------------------------------------------------
    # Usuário já autenticado
    # --------------------------------------------------------

    if "user" in session:
        return redirect(
            url_for("index")
        )

    # --------------------------------------------------------
    # POST legado
    # --------------------------------------------------------

    if request.method == "POST":

        username = request.form.get(
            "username",
            ""
        ).strip()

        password = request.form.get(
            "password",
            ""
        )

        # ----------------------------------------------------
        # NÃO RECOMENDADO PARA PRODUÇÃO
        # ----------------------------------------------------
        #
        # Mantido apenas para compatibilidade.
        #
        # O ideal é remover este login e utilizar somente
        # Microsoft Entra ID.
        #

        admin_user = os.getenv(
            "LOCAL_ADMIN_USER"
        )

        admin_password = os.getenv(
            "LOCAL_ADMIN_PASSWORD"
        )

        if (
            admin_user
            and admin_password
            and username == admin_user
            and password == admin_password
        ):

            session["user"] = {
                "name": username
            }

            return redirect(
                url_for("index")
            )

        return render_template(
            "login.html",
            error="Credenciais inválidas"
        )

    # --------------------------------------------------------
    # Microsoft
    # --------------------------------------------------------

    return redirect(
        url_for("login_microsoft")
    )


# ============================================================
# LOGOUT
# ============================================================

@app.route("/logout")
def logout():
    """
    Encerra a sessão local e registra logout.
    """

    session_token = session.get(
        "session_token"
    )

    user_id = session.get(
        "user_id"
    )

    # ========================================================
    # REGISTRA LOGOUT
    # ========================================================

    if session_token and user_id:

        conn = None

        try:

            conn = bdmonitoramento()

            if conn:

                registrar_logout(
                    conn,
                    user_id,
                    session_token
                )

        except Exception:

            traceback.print_exc()

        finally:

            if conn:
                conn.close()

    # ========================================================
    # LIMPA SESSÃO
    # ========================================================

    session.clear()

    # ========================================================
    # LOGOUT ENTRA ID
    # ========================================================

    tenant_id = os.getenv(
        "AZURE_TENANT_ID"
    )

    redirect_uri = url_for(
        "login",
        _external=True
    )

    logout_url = (
        f"https://login.microsoftonline.com/"
        f"{tenant_id}"
        f"/oauth2/v2.0/logout"
        f"?post_logout_redirect_uri="
        f"{redirect_uri}"
    )

    return redirect(
        logout_url
    )


# ============================================================
# HEARTBEAT
# ============================================================

@app.route(
    "/heartbeat",
    methods=["POST"]
)
def heartbeat():

    session_token = session.get(
        "session_token"
    )

    if not session_token:
        return (
            jsonify({
                "status": "expirada"
            }),
            401,
        )

    conn = None

    try:

        conn = bdmonitoramento()

        if not conn:
            return (
                jsonify({
                    "status": "erro",
                    "msg": "Erro na conexão."
                }),
                500,
            )

        ativo = atualizar_atividade_sessao(
            conn,
            session_token
        )

        if not ativo:

            session.clear()

            return (
                jsonify({
                    "status": "expirada"
                }),
                401,
            )

        return jsonify({
            "status": "ok"
        })

    except Exception as exc:

        traceback.print_exc()

        return (
            jsonify({
                "status": "erro",
                "msg": str(exc)
            }),
            500,
        )

    finally:

        if conn:
            conn.close()


# ============================================================
# DASHBOARD
# ============================================================

@app.route("/index")
def index():

    job = session.get(
        "user",
        {}
    ).get("job")

    if is_sustentacao(job):

        return render_template(
            "sustentacao/dashboard.html"
        )

    return render_template(
        "dashboard.html"
    )


@app.route("/dashboard")
def dashboard():

    return render_template(
        "dashboard.html"
    )


# ============================================================
# HOSTS
# ============================================================

@app.route("/hosts")
def hosts():

    job = session.get(
        "user",
        {}
    ).get("job")

    template = (
        "sustentacao/dashboard.html"
        if is_sustentacao(job)
        else "hosts.html"
    )

    return render_template(
        template
    )


# ============================================================
# BUSCA GLOBAL
# ============================================================

@app.route("/api/search")
def global_search():

    try:

        query = request.args.get(
            "q",
            ""
        ).strip().lower()

        if len(query) < 2:
            return jsonify([])

        resultados = []

        # ====================================================
        # HOSTS
        # ====================================================

        hosts = buscar_hosts_com_ip() or []

        for host in hosts:

            nome = (
                host.get("nome")
                or ""
            ).lower()

            ip = (
                host.get("ip")
                or ""
            ).lower()

            if (
                query in nome
                or query in ip
            ):

                resultados.append({
                    "type": "host",
                    "id": host.get("id"),
                    "label": (
                        f"{host.get('nome')} "
                        f"({host.get('ip')})"
                    ),
                })

        # ====================================================
        # GRUPOS
        # ====================================================

        grupos = (
            get_grupos_com_hosts()
            or []
        )

        for grupo in grupos:

            nome_grupo = (
                grupo.get("grupo")
                or ""
            )

            if query in nome_grupo.lower():

                resultados.append({
                    "type": "grupo",
                    "label": nome_grupo,
                })

        return jsonify(
            resultados[:20]
        )

    except Exception as exc:

        traceback.print_exc()

        return (
            jsonify({
                "error": str(exc)
            }),
            500,
        )


# ============================================================
# CLIENT MONITOR
# ============================================================

@app.route(
    "/portal/token",
    methods=["GET"]
)
def portal_get_token():

    if not API_CLIENTES:
        return (
            jsonify({
                "error": "HOSTCLIENT não configurado."
            }),
            500,
        )

    try:

        response = requests.post(
            f"{API_CLIENTES}/api/token",
            timeout=5,
        )

        response.raise_for_status()

        return jsonify(
            response.json()
        )

    except requests.RequestException as exc:

        return (
            jsonify({
                "error": str(exc)
            }),
            502,
        )


# ============================================================
# CLIENT MONITOR - GRUPOS
# ============================================================

@app.route(
    "/portal/grupos",
    methods=["GET"]
)
def portal_listar_grupos():

    if not API_CLIENTES:
        return (
            jsonify({
                "error": "HOSTCLIENT não configurado."
            }),
            500,
        )

    try:

        token_response = requests.post(
            f"{API_CLIENTES}/api/token",
            timeout=5,
        )

        token_response.raise_for_status()

        token = (
            token_response
            .json()
            .get("token")
        )

        if not token:

            return (
                jsonify({
                    "error": "Token não retornado."
                }),
                502,
            )

        response = requests.get(
            f"{API_CLIENTES}/api/grupos",
            headers={
                "Authorization":
                f"Bearer {token}"
            },
            timeout=10,
        )

        return (
            jsonify(response.json()),
            response.status_code,
        )

    except Exception as exc:

        traceback.print_exc()

        return (
            jsonify({
                "error": str(exc)
            }),
            502,
        )


# ============================================================
# CLIENT MONITOR - CRIAR USUÁRIO
# ============================================================

@app.route(
    "/portal/criar-usuario",
    methods=["POST"]
)
def portal_criar_usuario():

    if not API_CLIENTES:
        return (
            jsonify({
                "error": "HOSTCLIENT não configurado."
            }),
            500,
        )

    try:

        data = request.get_json(
            silent=True
        ) or {}

        token_response = requests.post(
            f"{API_CLIENTES}/api/token",
            timeout=5,
        )

        token_response.raise_for_status()

        token = (
            token_response
            .json()
            .get("token")
        )

        if not token:

            return (
                jsonify({
                    "error": "Token não retornado."
                }),
                502,
            )

        create_response = requests.post(
            f"{API_CLIENTES}/api/users",
            headers={
                "Authorization":
                f"Bearer {token}",
                "Content-Type":
                "application/json",
            },
            json=data,
            timeout=10,
        )

        return (
            jsonify(
                create_response.json()
            ),
            create_response.status_code,
        )

    except Exception as exc:

        traceback.print_exc()

        return (
            jsonify({
                "error": str(exc)
            }),
            502,
        )


# ============================================================
# CLIENTE
# ============================================================

@app.route("/cliente")
def cliente():

    return render_template(
        "cliente.html"
    )


# ============================================================
# INCIDENTES
# ============================================================

@app.route("/incidentes")
def incidentes():

    conn = conectar_postgres()

    try:

        dados = (
            buscar_incidentes_ativos_do_dia(
                conn,
                redis_client=None
            )
        )

    finally:

        conn.close()

    return render_template(
        "incidentes.html",
        incidentes=dados
    )


@app.route("/incidentes/json")
def incidentes_json():

    conn = conectar_postgres()

    try:

        dados = (
            buscar_incidentes_ativos_do_dia(
                conn,
                redis_client=None
            )
        )

    finally:

        conn.close()

    return jsonify(dados)


# ============================================================
# DADOS
# ============================================================

@app.route("/dados")
def dados():

    return jsonify(
        coletar_dados()
    )


# ============================================================
# GRUPOS
# ============================================================

@app.route("/grupos")
def grupo():

    return jsonify(
        get_grupos_com_hosts()
    )


# ============================================================
# HOSTS POR GRUPO
# ============================================================

@app.route(
    "/hosts/grupo/<string:grupo_nome>"
)
def hosts_por_grupo(grupo_nome):

    grupos = (
        get_grupos_com_hosts()
        or []
    )

    grupo_selecionado = next(
        (
            grupo
            for grupo in grupos
            if grupo.get("grupo", "").lower()
            == grupo_nome.lower()
        ),
        None,
    )

    if not grupo_selecionado:

        return (
            "Grupo não encontrado",
            404
        )

    job = session.get(
        "user",
        {}
    ).get("job")

    template = (
        "sustentacao/hosts_group.html"
        if is_sustentacao(job)
        else "hosts_group.html"
    )

    return render_template(
        template,
        grupo=grupo_selecionado,
        hosts=grupo_selecionado.get(
            "hosts",
            []
        ),
    )





@app.route("/api/host_details/<int:hostid>")
def host_metrics(hostid):

    print("=" * 80)
    print("[HOST DETAILS] Requisição recebida")
    print(f"[HOST DETAILS] hostid = {hostid}")
    print("=" * 80)

    try:

        cache_key = f"host_metrics:{hostid}"

        print(
            f"[REDIS] chave = {cache_key}"
        )

        cached = redis_client.get(cache_key)

        if cached:

            print(
                f"[REDIS] CACHE HIT hostid={hostid}"
            )

            return jsonify(
                json.loads(cached)
            )

        print(
            f"[REDIS] CACHE MISS hostid={hostid}"
        )

        print(
            f"[POSTGRES] buscando métricas "
            f"hostid={hostid}"
        )

        data = get_host_metrics(hostid)

        print(
            f"[POSTGRES] retorno recebido "
            f"hostid={hostid}"
        )

        if not data:

            print(
                f"[POSTGRES] nenhum dado "
                f"hostid={hostid}"
            )

            return jsonify({
                "error":
                    "Host não encontrado"
            }), 404

        data = normalize_for_json(data)

        print(
            f"[REDIS] salvando "
            f"{cache_key}"
        )

        redis_client.setex(
            cache_key,
            85,
            json.dumps(data)
        )

        print(
            f"[REDIS] CACHE SET "
            f"hostid={hostid}"
        )

        print(
            f"[API] retornando dados "
            f"hostid={hostid}"
        )

        return jsonify(data)

    except Exception as e:

        import traceback

        print("=" * 80)
        print(
            f"[API] ERRO hostid={hostid}"
        )
        print(
            f"[API] {type(e).__name__}: {e}"
        )
        print("=" * 80)

        traceback.print_exc()

        return jsonify({
            "error": str(e)
        }), 500

# ============================================================
# AVATAR
# ============================================================

@app.route("/avatar")
def avatar():

    user = session.get(
        "user"
    )

    if not user:
        abort(401)

    name = (
        user.get("name")
        or "U"
    )

    letra = name[0].upper()

    size = 128

    img = Image.new(
        "RGB",
        (size, size),
        color="#155e75"
    )

    draw = ImageDraw.Draw(
        img
    )

    try:

        font = ImageFont.truetype(
            "arial.ttf",
            67
        )

    except Exception:

        font = ImageFont.load_default()

    x0, y0, x1, y1 = (
        draw.textbbox(
            (0, 0),
            letra,
            font=font
        )
    )

    w = x1 - x0
    h = y1 - y0

    draw.text(
        (
            (size - w) / 2,
            (size - h) / 2
        ),
        letra,
        fill="white",
        font=font
    )

    buffer = BytesIO()

    img.save(
        buffer,
        format="PNG"
    )

    buffer.seek(0)

    return Response(
        buffer.getvalue(),
        mimetype="image/png"
    )


# ============================================================
# SALVAR IP
# ============================================================

@app.route(
    "/api/salvar-ip",
    methods=["POST"]
)
def salvar_ip():

    data = (
        request.get_json(
            silent=True
        )
        or {}
    )

    ip = data.get("ip")
    user_agent = data.get(
        "user_agent"
    )
    plataforma = data.get(
        "plataforma"
    )

    print(
        "IP recebido:",
        ip
    )

    print(
        "User-Agent:",
        user_agent
    )

    print(
        "Plataforma:",
        plataforma
    )

    return jsonify({
        "status": "ok"
    })


# ============================================================
# MONITORAMENTO
# ============================================================

@app.route(
    "/api/moni",
    methods=["GET"]
)
def moni():

    conn = None

    try:

        conn = conectar_postgres()

        incidentes = (
            buscar_incidentes_ativos_do_dia(
                conn
            )
            or []
        )

        totais_hosts = (
            get_hosts_totais(
                conn
            )
            or {}
        )

        return jsonify({

            "total_incidentes":
                len(incidentes),

            "online":
                totais_hosts.get(
                    "online",
                    0
                ),

            "offline":
                totais_hosts.get(
                    "offline",
                    0
                ),

            "sem_acesso":
                totais_hosts.get(
                    "sem_acesso",
                    0
                ),

            "manutencao":
                totais_hosts.get(
                    "manutencao",
                    0
                ),

        })

    except Exception as exc:

        traceback.print_exc()

        return (
            jsonify({
                "erro": str(exc)
            }),
            500,
        )

    finally:

        if conn:
            conn.close()


# ============================================================
# PROBLEMAS 24H
# ============================================================

@app.route(
    "/api/problemas-24h",
    methods=["GET"]
)
def problemas_24h():

    conn = None

    try:

        conn = conectar_postgres()

        dados = get_problemas_24h_cache(
            conn
        )

        return jsonify(
            dados
        )

    except Exception as exc:

        traceback.print_exc()

        return (
            jsonify({
                "erro": str(exc)
            }),
            500,
        )

    finally:

        if conn:
            conn.close()


# ============================================================
# TEMA
# ============================================================

@app.route(
    "/api/theme",
    methods=["POST"]
)
def alterar_tema():

    user_id = session.get(
        "user_id"
    )

    if not user_id:

        return (
            jsonify({
                "erro":
                "Não autenticado"
            }),
            401,
        )

    data = (
        request.get_json(
            silent=True
        )
        or {}
    )

    theme = data.get(
        "theme"
    )

    if theme not in (
        "light",
        "dark"
    ):

        return (
            jsonify({
                "erro":
                "Tema inválido"
            }),
            400,
        )

    sucesso = update_user_theme(
        user_id,
        theme
    )

    if sucesso:

        session["theme"] = theme

        return jsonify({
            "success": True
        })

    return (
        jsonify({
            "erro":
            "Falha ao salvar tema"
        }),
        500,
    )


# ============================================================
# RELATÓRIO
# ============================================================

@app.route("/relatorio")
def relatorio():

    grupos = get_grupos()

    return render_template(
        "relatorio.html",
        grupos=grupos
    )


# ============================================================
# RELATÓRIO - HOSTS
# ============================================================

@app.route(
    "/api/relatorio/hosts/<int:groupid>"
)
def api_hosts(groupid):

    return jsonify(
        get_hosts_por_grupo(
            groupid
        )
    )


# ============================================================
# RELATÓRIO - MÉTRICAS
# ============================================================

@app.route(
    "/api/relatorio/metricas/<int:hostid>"
)
def api_metricas(hostid):

    metricas = get_host_metrics(
        hostid
    )

    if not metricas:

        return (
            jsonify({
                "erro":
                "Host não encontrado"
            }),
            404,
        )

    return jsonify(
        metricas
    )


# ============================================================
# GRÁFICOS
# ============================================================

ITEMS_GRAFICOS = {

    "cpu":
        "system.cpu.util[,idle]",

    "memoria":
        "vm.memory.utilization",

    "ping":
        "icmpping",

    "latencia":
        "icmppingsec",

}


# ============================================================
# TODOS OS GRÁFICOS
# ============================================================

@app.route(
    "/api/relatorio/todos-graficos"
)
def api_todos_graficos():

    hostid = request.args.get(
        "hostid",
        type=int
    )

    inicio = request.args.get(
        "inicio"
    )

    fim = request.args.get(
        "fim"
    )

    if not all([
        hostid,
        inicio,
        fim
    ]):

        return (
            jsonify({
                "erro":
                "Parâmetros: "
                "hostid, inicio, fim"
            }),
            400,
        )

    resultado = {}

    for nome, key in (
        ITEMS_GRAFICOS.items()
    ):

        resultado[nome] = (
            get_grafico_host(
                hostid,
                key,
                inicio,
                fim
            )
        )

    return jsonify(
        resultado
    )


# ============================================================
# MULTI HOST
# ============================================================

@app.route(
    "/api/relatorio/multi-host",
    methods=["POST"]
)
def api_multi_host():

    body = (
        request.get_json(
            silent=True
        )
        or {}
    )

    ids = body.get(
        "hostids",
        []
    )

    inicio = body.get(
        "inicio"
    )

    fim = body.get(
        "fim"
    )

    if (
        not ids
        or not inicio
        or not fim
    ):

        return (
            jsonify({
                "erro":
                "Parâmetros: "
                "hostids, inicio, fim"
            }),
            400,
        )

    resultado = []

    for hostid in ids:

        try:

            hostid = int(hostid)

        except (
            TypeError,
            ValueError
        ):

            continue

        metricas = get_host_metrics(
            hostid
        )

        if not metricas:
            continue

        periodo = (
            get_relatorio_host_inteligente(
                hostid,
                inicio,
                fim
            )
        )

        graficos = {}

        for nome, key in (
            ITEMS_GRAFICOS.items()
        ):

            graficos[nome] = (
                get_grafico_host(
                    hostid,
                    key,
                    inicio,
                    fim
                )
            )

        resultado.append({

            "metricas":
                metricas,

            "periodo":
                periodo,

            "graficos":
                graficos,

        })

    return jsonify(
        resultado
    )


# ============================================================
# RELATÓRIO PRINT
# ============================================================

@app.route(
    "/relatorio/print"
)
def relatorio_print():

    hostids = request.args.get(
        "hostids"
    )

    inicio = request.args.get(
        "inicio"
    )

    fim = request.args.get(
        "fim"
    )

    if (
        not hostids
        or not inicio
        or not fim
    ):

        return (
            "Parâmetros inválidos",
            400
        )

    try:

        ids = [
            int(x)
            for x in hostids.split(",")
            if x.strip()
        ]

    except ValueError:

        return (
            "Host IDs inválidos",
            400
        )

    dados = []

    for hostid in ids:

        metricas = get_host_metrics(
            hostid
        )

        if not metricas:
            continue

        periodo = (
            get_relatorio_host_periodo(
                hostid,
                inicio,
                fim
            )
        )

        graficos = {}

        for nome, key in (
            ITEMS_GRAFICOS.items()
        ):

            graficos[nome] = (
                get_grafico_host(
                    hostid,
                    key,
                    inicio,
                    fim
                )
            )

        dados.append({

            "metricas":
                metricas,

            "periodo":
                periodo,

            "graficos":
                graficos,

        })

    return render_template(
        "relatorio_print.html",
        dados=dados,
        inicio=inicio,
        fim=fim
    )


# ============================================================
# RELATÓRIO INTELIGENTE
# ============================================================

@app.route(
    "/api/relatorio/inteligente/<int:hostid>"
)
def relatorio_inteligente(hostid):

    inicio = request.args.get(
        "inicio"
    )

    fim = request.args.get(
        "fim"
    )

    agrupamento = request.args.get(
        "agrupamento",
        "15min"
    )

    if not inicio or not fim:

        return (
            jsonify({
                "erro":
                "Informe inicio e fim."
            }),
            400,
        )

    agrupamentos_validos = {
        "15min",
        "hora",
        "dia",
        "auto",
    }

    if agrupamento not in (
        agrupamentos_validos
    ):

        return (
            jsonify({
                "erro":
                "agrupamento inválido"
            }),
            400,
        )

    try:

        dados = (
            get_relatorio_host_inteligente(
                hostid=hostid,
                inicio=inicio,
                fim=fim,
                agrupamento=agrupamento
            )
        )

        return jsonify({

            "hostid":
                hostid,

            "inicio":
                inicio,

            "fim":
                fim,

            "agrupamento":
                agrupamento,

            "dados":
                dados,

        })

    except Exception as exc:

        traceback.print_exc()

        return (
            jsonify({
                "erro":
                f"Erro ao gerar relatório: {exc}"
            }),
            500,
        )


# ============================================================
# GET IP
# ============================================================

@app.route("/getip")
def getip():

    try:

        dados = (
            buscar_hosts_com_ip()
        )

        return jsonify(
            dados
        )

    except Exception as exc:

        return (
            jsonify({
                "erro": str(exc)
            }),
            500,
        )


@app.route(
    "/getip/<int:hostid>"
)
def getip_por_host(hostid):

    try:

        dados = (
            buscar_host_por_id(
                hostid
            )
        )

        return jsonify(
            dados
        )

    except Exception as exc:

        return (
            jsonify({
                "erro": str(exc)
            }),
            500,
        )


# ============================================================
# GUACAMOLE
# ============================================================

@app.route("/portal")
def portal():

    token_data = get_token()

    connections = get_connections(
        token_data
    )

    return render_template(
        "portal.html",
        connections=connections,
        token=token_data.get(
            "authToken"
        ),
        data_source=token_data.get(
            "dataSource"
        ),
    )


# ============================================================
# GUACAMOLE CONNECTION DETAIL
# ============================================================

@app.route(
    "/api/connections/<connection_id>"
)
def api_connection_detail(
    connection_id
):

    try:

        token_data = get_token()

        data_source = token_data[
            "dataSource"
        ]

        token = token_data[
            "authToken"
        ]

        url = (
            f"{GUAC_URL}"
            f"/api/session/data/"
            f"{data_source}"
            f"/connections/"
            f"{connection_id}"
        )

        response = requests.get(
            url,
            params={
                "token": token
            },
            timeout=10,
        )

        return (
            response.text,
            response.status_code,
            {
                "Content-Type":
                "application/json"
            },
        )

    except Exception as exc:

        traceback.print_exc()

        return (
            jsonify({
                "erro": str(exc)
            }),
            502,
        )


# ============================================================
# GUACAMOLE PARAMETERS
# ============================================================

@app.route(
    "/api/connections/<connection_id>/parameters"
)
def api_connection_parameters(
    connection_id
):

    try:

        token_data = get_token()

        data_source = token_data[
            "dataSource"
        ]

        token = token_data[
            "authToken"
        ]

        url = (
            f"{GUAC_URL}"
            f"/api/session/data/"
            f"{data_source}"
            f"/connections/"
            f"{connection_id}"
            f"/parameters"
        )

        response = requests.get(
            url,
            params={
                "token": token
            },
            timeout=10,
        )

        return (
            response.text,
            response.status_code,
            {
                "Content-Type":
                "application/json"
            },
        )

    except Exception as exc:

        traceback.print_exc()

        return (
            jsonify({
                "erro": str(exc)
            }),
            502,
        )


# ============================================================
# RDP
# ============================================================

@app.route(
    "/rdp/<connection_id>"
)
def abrir_rdp(connection_id):

    try:

        token_data = get_token()

        token = token_data[
            "authToken"
        ]

        url = (
            f"{GUAC_URL}"
            f"/#/client/"
            f"{connection_id}"
            f"?token={token}"
        )

        print(
            "Abrindo conexão:",
            connection_id
        )

        return redirect(
            url
        )

    except Exception as exc:

        traceback.print_exc()

        return (
            jsonify({
                "erro": str(exc)
            }),
            500,
        )


# ============================================================
# CONNECT
# ============================================================

@app.route(
    "/connect/<int:connection_id>"
)
def conectar_redirect(
    connection_id
):

    try:

        token_data = get_token()

        url = gerar_link_conexao(
            str(connection_id),
            token_data
        )

        return redirect(
            url
        )

    except Exception as exc:

        traceback.print_exc()

        return (
            jsonify({
                "erro": str(exc)
            }),
            500,
        )


# ============================================================
# API CONNECT
# ============================================================

@app.route(
    "/api/connect",
    methods=["POST"]
)
def api_connect():

    try:

        data = (
            request.get_json(
                silent=True
            )
            or {}
        )

        print(
            "DATA RECEBIDA:",
            data
        )

        nome = data.get(
            "nome"
        )

        porta = data.get(
            "porta"
        )

        if not nome:

            return (
                jsonify({
                    "error":
                    "Nome não enviado"
                }),
                400,
            )

        user = session.get(
            "user"
        )

        if not user:

            return (
                jsonify({
                    "error":
                    "Usuário não autenticado"
                }),
                401,
            )

        email = user.get(
            "email"
        )

        if not email:

            return (
                jsonify({
                    "error":
                    "Email do usuário não encontrado"
                }),
                400,
            )

        print(
            "USUÁRIO:",
            email
        )

        url = conectar_ou_criar(
            nome,
            porta,
            email
        )

        return jsonify({
            "url": url
        })

    except Exception as exc:

        traceback.print_exc()

        return (
            jsonify({
                "error": str(exc)
            }),
            500,
        )


# ============================================================
# IMAGEM
# ============================================================

@app.route("/imagem/")
def imagem():

    return send_from_directory(
        os.path.join(
            app.static_folder,
            "img"
        ),
        "capa_relatorio.jpg"
    )


# ============================================================
# IMPRIMIR CAPA
# ============================================================

@app.route(
    "/imprimircapa/"
)
def imprimir_capa():

    return render_template(
        "printimagem.html"
    )


# ============================================================
# SCRIPT
# ============================================================

@app.route("/script")
def script():

    return render_template(
        "script.html"
    )


# ============================================================
# ERROR HANDLERS
# ============================================================

@app.errorhandler(401)
def unauthorized(error):

    return (
        jsonify({
            "erro":
            "Não autenticado."
        }),
        401,
    )


@app.errorhandler(404)
def not_found(error):

    # Se for API, retorna JSON.
    if request.path.startswith("/api/"):

        return (
            jsonify({
                "erro":
                "Endpoint não encontrado."
            }),
            404,
        )

    return (
        render_template(
            "404.html"
        ),
        404,
    )


@app.errorhandler(500)
def internal_error(error):

    traceback.print_exc()

    if request.path.startswith("/api/"):

        return (
            jsonify({
                "erro":
                "Erro interno do servidor."
            }),
            500,
        )

    return (
        render_template(
            "500.html"
        ),
        500,
    )


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    debug = (
        os.getenv(
            "FLASK_DEBUG",
            "false"
        ).lower()
        == "true"
    )

    host = os.getenv(
        "FLASK_HOST",
        "127.0.0.1"
    )

    port = int(
        os.getenv(
            "FLASK_PORT",
            "8000"
        )
    )

    print("=" * 60)
    print("PORTAL FLASK")
    print("=" * 60)
    print(
        f"Host : {host}"
    )
    print(
        f"Porta: {port}"
    )
    print(
        f"Debug: {debug}"
    )
    print(
        f"Env  : {APP_ENV}"
    )
    print("=" * 60)

    app.run(
        host=host,
        port=port,
        debug=debug,
        threaded=True,
    )