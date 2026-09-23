def normalize_user_profile(graph_data: dict) -> dict:
    """
    Docstring para normalize_user_profile

    :param graph_data: Descrição
    :type graph_data: dict
    :return: Descrição
    :rtype: dict
    """
    if not graph_data:
        raise ValueError("Dados do usuário vazios")

    user = {
        "azure_oid": graph_data.get("id"),
        "name": graph_data.get("givenName") or graph_data.get("displayName"),
        "email": graph_data.get("mail") or graph_data.get("userPrincipalName"),
        "job_title": graph_data.get("jobTitle"),
        "department": graph_data.get("department"),
    }

    if not user["azure_oid"]:
        raise ValueError("Azure OID não encontrado")

    return user
