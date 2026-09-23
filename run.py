"""
Arquivo principal para inicialização do Portal.
Responsável por iniciar a aplicação Flask.
"""
from flask import Flask, request
from werkzeug.middleware.proxy_fix import ProxyFix
from waitress import serve
from app import app


serve(app, host="0.0.0.0", port=8060)

app = Flask(__name__)

app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)
