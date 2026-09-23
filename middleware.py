from flask import session, redirect, url_for, request
from data import bdmonitoramento, validar_sessao, atualizar_atividade_sessao

# Rotas que não precisam de login
ROTAS_PUBLICAS = ["/", "/login", "/auth/callback", "/logout", "/static"]


def rota_publica(path):
    """
    Docstring para rota_publica

    :param path: Descrição
    """
    return any(path.startswith(r) for r in ROTAS_PUBLICAS)


def middleware_autenticacao(app):
    """
    Docstring para middleware_autenticacao

    :param app: Descrição
    """

    @app.before_request
    def validar_login():
        path = request.path

        # Ignora rotas públicas
        if rota_publica(path):
            return None

        session_token = session.get("session_token")
        if not session_token:
            return redirect(url_for("login"))

        conn = bdmonitoramento()
        if not conn:
            session.clear()
            return redirect(url_for("login"))

        sessao = validar_sessao(conn, session_token)

        if not sessao:
            conn.close()
            session.clear()
            return redirect(url_for("login"))

        # Atualiza última atividade
        atualizar_atividade_sessao(conn, session_token)
        conn.close()

        return None
