"""Configuração lida do ambiente (.env).

O provedor de LLM é escolhido por COMPENDIO_PROVEDOR (gemini | claude). Cada um
tem modelos padrão; COMPENDIO_MODELO_RAPIDO / _FORTE sobrescrevem.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - dotenv é dependência, mas não quebra sem ela
    def load_dotenv(*_a, **_k):
        return False


PROVEDORES = {
    # rápido = trabalho em volume (extrair cada trecho); forte = decisões (mapear, descobrir esquema, validar)
    # vários modelos separados por vírgula = cadeia de reserva: se o primeiro estiver
    # indisponível (503/429) depois das retentativas, a chamada passa para o próximo
    "gemini": {"chave": "GEMINI_API_KEY",
               "rapido": "gemini-3.5-flash-lite,gemini-3.1-flash-lite",
               "forte": "gemini-3.8-flash,gemini-3.6-flash"},
    "claude": {"chave": "ANTHROPIC_API_KEY", "rapido": "claude-haiku-5-5", "forte": "claude-sonnet-5-5"},
}


@dataclass(frozen=True)
class Config:
    api_key: str | None
    modelo_rapido: str
    modelo_forte: str
    max_tokens: int
    banco: Path
    provedor: str = "gemini"
    timeout_s: float = 300.0  # tempo máximo esperando uma resposta (o Gemini usa isso como prazo no servidor)

    @property
    def nome_da_chave(self) -> str:
        return PROVEDORES[self.provedor]["chave"]


def carregar(env_file: str | os.PathLike | None = ".env", provedor: str | None = None) -> Config:
    if env_file:
        load_dotenv(env_file)
    provedor = (provedor or os.getenv("COMPENDIO_PROVEDOR") or "gemini").strip().lower()
    if provedor not in PROVEDORES:
        raise ValueError(f"COMPENDIO_PROVEDOR inválido: {provedor!r} (use {' ou '.join(PROVEDORES)})")
    p = PROVEDORES[provedor]
    return Config(
        api_key=os.getenv(p["chave"]) or None,
        modelo_rapido=os.getenv("COMPENDIO_MODELO_RAPIDO") or p["rapido"],
        modelo_forte=os.getenv("COMPENDIO_MODELO_FORTE") or p["forte"],
        max_tokens=int(os.getenv("COMPENDIO_MAX_TOKENS", "4096")),
        banco=Path(os.getenv("COMPENDIO_BANCO", "data/compendio.db")),
        provedor=provedor,
        timeout_s=float(os.getenv("COMPENDIO_TIMEOUT", "300")),
    )
