import os
import msal
import requests
import base64
import uuid
from pathlib import Path
from msal import SerializableTokenCache
from user_mapper import normalize_user_profile
from dotenv import load_dotenv
from flask import request
from utils import get_client_ip

CLIENT_ID = os.getenv("AZURE_CLIENT_ID")
CLIENT_SECRET = os.getenv("AZURE_CLIENT_SECRET")
TENANT_ID = os.getenv("AZURE_TENANT_ID")
REDIRECT_URI = os.getenv("AZURE_REDIRECT_URI")

BASE_DIR = Path(__file__).resolve().parent

print("ENV:", BASE_DIR / ".env")

load_dotenv(BASE_DIR / ".env", override=True)

print("="*80)
print("CLIENT_ID:", os.getenv("AZURE_CLIENT_ID"))
print("TENANT:", os.getenv("AZURE_TENANT_ID"))
print("SECRET:", os.getenv("AZURE_CLIENT_SECRET"))
print("SECRET LEN:", len(os.getenv("AZURE_CLIENT_SECRET")))
print("="*80)

AUTHORITY = f"https://login.microsoftonline.com/{TENANT_ID}"
SCOPE = [
    "User.Read",
    "GroupMember.Read.All",
    "AuditLog.Read.All",
]

# ======================================================
# CACHE MSAL (SESSION)
# ======================================================
msal_cache = SerializableTokenCache()


def build_msal_app():
    """
    Docstring para build_msal_app
    """
    return msal.ConfidentialClientApplication(
        CLIENT_ID,
        authority=AUTHORITY,
        client_credential=CLIENT_SECRET,
        token_cache=msal_cache,
    )


# ======================================================
# MSAL APP COM CACHE
# ======================================================


# ======================================================
# URL DE LOGIN MICROSOFT
# ======================================================
def build_auth_url():
    """
    Docstring para build_auth_url
    """
    app = build_msal_app()
    return app.get_authorization_request_url(
        scopes=SCOPE, redirect_uri=REDIRECT_URI, prompt="select_account"
    )


# ======================================================
# TOKEN SILENCIOSO (EVITA REL0GIN)
# ======================================================
def get_token_silent():
    """
    Docstring para get_token_silent
    """
    app = build_msal_app()
    accounts = app.get_accounts()

    if not accounts:
        return None

    result = app.acquire_token_silent(scopes=SCOPE, account=accounts[0])

    return result


# ======================================================
# FOTO DO USUÁRIO (GRAPH API)
# ======================================================


def get_user_profile(access_token):
    """
    Docstring para get_user_profile

    :param access_token: Descrição
    """
    headers = {"Authorization": f"Bearer {access_token}"}

    response = requests.get(
        "https://graph.microsoft.com/v1.0/me", headers=headers, timeout=10
    )

    data = response.json()
    print("DEBUG USER PROFILE:", data)

    user = normalize_user_profile(data)


    print("DEBUG USER PROFILE (NORMALIZADO):", user)
    return user


