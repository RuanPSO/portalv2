import requests


GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"


class AzureService:

    def __init__(self, access_token: str):
        self.access_token = access_token
        self.headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json"
        }

    # ==============================
    # 🔹 DADOS BÁSICOS DO USUÁRIO
    # ==============================
    def get_user_profile(self):
        """
        Retorna:
        Nome, Email, Departamento, Cargo, OID
        """
        url = f"{GRAPH_BASE_URL}/me"
        response = requests.get(url, headers=self.headers)
        response.raise_for_status()

        data = response.json()

        return {
            "oid": data.get("id"),
            "nome": data.get("displayName"),
            "email": data.get("mail") or data.get("userPrincipalName"),
            "departamento": data.get("department"),
            "cargo": data.get("jobTitle")
        }

    # ==============================
    # 🔹 GRUPOS DO USUÁRIO
    # ==============================
    def get_user_groups(self):
        """
        Retorna lista de grupos do usuário
        """
        url = f"{GRAPH_BASE_URL}/me/memberOf"
        response = requests.get(url, headers=self.headers)
        response.raise_for_status()

        data = response.json()

        grupos = []
        for group in data.get("value", []):
            if group["@odata.type"] == "#microsoft.graph.group":
                grupos.append({
                    "id": group.get("id"),
                    "nome": group.get("displayName")
                })

        return grupos

    # ==============================
    # 🔹 SIGN-IN LOGS (AUDITORIA)
    # ==============================
    def get_last_signin_info(self, user_oid: str):
        """
        Retorna:
        IP de login
        Sistema operacional
        Localização
        Device ID
        """

        url = (
            f"{GRAPH_BASE_URL}/auditLogs/signIns"
            f"?$filter=userId eq '{user_oid}'"
            f"&$top=1"
        )

        response = requests.get(url, headers=self.headers)
        response.raise_for_status()

        data = response.json()
        logs = data.get("value", [])

        if not logs:
            return None

        log = logs[0]

        return {
            "ip_login": log.get("ipAddress"),
            "sistema_operacional": log.get("deviceDetail", {}).get("operatingSystem"),
            "device_id": log.get("deviceDetail", {}).get("deviceId"),
            "localizacao": {
                "cidade": log.get("location", {}).get("city"),
                "estado": log.get("location", {}).get("state"),
                "pais": log.get("location", {}).get("countryOrRegion")
            },
            "app_usado": log.get("appDisplayName"),
            "data_login": log.get("createdDateTime")
        }