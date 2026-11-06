"""Expressões de dados (3d6+2, 1d8 + 1d6, d20...).

Fica fora do LLM de propósito: é determinístico, verificável e é exatamente o
que o VTT vai precisar para rolar o efeito a partir do compêndio.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_DADO = r"\d*\s*[dD]\s*\d+"
_TERMO = rf"(?:{_DADO}|\d+)"
_EXPR = re.compile(rf"(?<![\w]){_TERMO}(?:\s*[+\-−]\s*{_TERMO})*(?![\w])")
_TEM_DADO = re.compile(_DADO)
_PARTE = re.compile(r"([+\-])?(\d*)d(\d+)|([+\-])?(\d+)")


@dataclass(frozen=True)
class Termo:
    quantidade: int  # 0 para constante
    faces: int  # 0 para constante
    constante: int = 0
    sinal: int = 1


def normalizar(expr: str) -> str:
    """'2D8 + 1d6' -> '2d8+1d6'. Levanta ValueError se não houver dado."""
    limpo = re.sub(r"\s+", "", expr).replace("−", "-").replace("D", "d")
    if not _TEM_DADO.search(limpo):
        raise ValueError(f"sem expressão de dados: {expr!r}")
    if not re.fullmatch(rf"{_TERMO}(?:[+\-]{_TERMO})*".replace(r"\s*", ""), limpo):
        raise ValueError(f"expressão de dados inválida: {expr!r}")
    return re.sub(r"(?<![\d])d", "1d", limpo)


def extrair(texto: str) -> list[str]:
    """Todas as expressões de dados de um texto, normalizadas, na ordem em que aparecem."""
    achados: list[str] = []
    for m in _EXPR.finditer(texto or ""):
        bruto = m.group(0)
        if _TEM_DADO.search(bruto):
            achados.append(normalizar(bruto))
    return achados


def termos(expr: str) -> list[Termo]:
    """Quebra uma expressão normalizada em termos — o VTT rola cada um."""
    resultado: list[Termo] = []
    for m in _PARTE.finditer(normalizar(expr)):
        if m.group(3):
            sinal = -1 if m.group(1) == "-" else 1
            resultado.append(Termo(quantidade=int(m.group(2) or 1), faces=int(m.group(3)), sinal=sinal))
        elif m.group(5):
            sinal = -1 if m.group(4) == "-" else 1
            resultado.append(Termo(quantidade=0, faces=0, constante=int(m.group(5)), sinal=sinal))
    return resultado


def faixa(expr: str) -> tuple[int, int]:
    """Mínimo e máximo possíveis — útil para validar o que o LLM extraiu."""
    minimo = maximo = 0
    for t in termos(expr):
        if t.faces:
            lo, hi = t.quantidade, t.quantidade * t.faces
        else:
            lo = hi = t.constante
        if t.sinal < 0:
            lo, hi = -hi, -lo
        minimo += lo
        maximo += hi
    return minimo, maximo
