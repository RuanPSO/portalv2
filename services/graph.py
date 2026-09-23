import requests


def get_user_photo(access_token):
    headers = {"Authorization": f"Bearer {access_token}"}

    response = requests.get(
        "https://graph.microsoft.com/v1.0/me/photo/$value", headers=headers, timeout=10
    )

    if response.status_code == 200:
        return response.content  # bytes da imagem

    return None
