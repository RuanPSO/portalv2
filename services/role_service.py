SUSTENTACAO_TITULOS = {
    "Analista de Suporte Técnico Jr",
    "Analista de Suporte Técnico Jr.",
    "Analista de Suporte Técnico Sênior",
    "Analista Técnico Jr",
    "Analista Técnico Pl",
    "Analista Técnico",
    "Coordenador Sustentação",
    "Líder Técnico",
}

def is_sustentacao(job_title: str) -> bool:
    if not job_title:
        return False

    return job_title.strip() in SUSTENTACAO_TITULOS