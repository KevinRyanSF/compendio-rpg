"""Comparação entre uma saída do sistema e o gold set.

É a mesma lógica para o revisor visual e para as métricas do relatório, então o
número que aparece na tela é o número que vai para a tabela.

Formato de uma saída (`.jsonl`, uma entrada por linha) — o mesmo das linhas
`entrada` do gold:

    {"sistema": "Ordem Paranormal", "categoria_canonica": "efeito_sobrenatural",
     "categoria_no_livro": "Ritual", "nome": "Arma Atroz", "paginas": [133, 133],
     "atributos": {"circulo": 1, "alcance": "toque", ...}, "descricao": "..."}

As chaves dos atributos podem ser as do sistema ("circulo", "tempo_de_conjuracao"):
elas são traduzidas para as canônicas antes de comparar.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .schema import canonico


# ------------------------------------------------------------------ leitura

def ler_jsonl(caminho: str | Path) -> list[dict]:
    with Path(caminho).open(encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def salvar_jsonl(linhas: Iterable[dict], caminho: str | Path) -> None:
    caminho = Path(caminho)
    tmp = caminho.with_suffix(caminho.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as f:
        for d in linhas:
            f.write(json.dumps(d, ensure_ascii=False) + "\n")
    tmp.replace(caminho)


# ------------------------------------------------------------- normalização

def norm(valor: Any) -> str:
    """Texto comparável: sem acento, minúsculo, espaços simples, sem hifenização de linha."""
    if isinstance(valor, bool):
        return "sim" if valor else "nao"
    texto = canonico.normalizar(str(valor)).replace("￾", "")
    texto = re.sub(r"(\w)- (\w)", r"\1\2", texto)
    return texto.strip(" .;:,")


def variantes(n: str) -> set[str]:
    """Formas equivalentes de um valor já normalizado: plural/singular e 'd4' = '1d4'."""
    vs = {n, n + "s", n.rstrip("s"), re.sub(r"al$", "ais", n), re.sub(r"ais$", "al", n), n.replace(" ", "")}
    vs |= {re.sub(r"\b1d(\d+)", r"d\1", v) for v in list(vs)}
    return {v for v in vs if v}


def chave_canonica(chave: str) -> str:
    return canonico.atributo_por_termo(chave.replace("_", " ")) or canonico.atributo_por_termo(chave) or chave


def _como_lista(valor: Any) -> list:
    return list(valor) if isinstance(valor, (list, tuple, set)) else [valor]


def valores_batem(esperado: Any, obtido: Any) -> bool:
    if obtido is None:
        return False
    if isinstance(esperado, bool):
        return norm(obtido) in ({"sim", "true", "verdadeiro", "1"} if esperado else {"nao", "false", "falso", "0", ""})
    if isinstance(esperado, list):
        texto = " | ".join(norm(v) for v in _como_lista(obtido))
        return all(norm(e) in texto for e in esperado)
    ne, no = norm(esperado), " | ".join(norm(v) for v in _como_lista(obtido))
    if not ne:
        return no in ("", "-", "—", "–")
    if ne == no or any(v in no or v in no.replace(" ", "") for v in variantes(ne)):
        return True
    if isinstance(esperado, (int, float)):
        numero = re.search(r"-?\d+", no)
        return bool(numero) and int(numero.group()) == int(esperado)
    return False


# --------------------------------------------------------------- comparação

@dataclass
class ComparacaoAtributo:
    chave: str
    esperado: Any
    obtido: Any
    bate: bool
    fora_do_recorte: bool = False
    chave_obtida: str | None = None  # valor certo, mas guardado com outro nome de campo


@dataclass
class Item:
    status: str  # acerto | faltou | sobrou | indevido | opcional | fora
    nome: str
    gold: dict | None = None
    saida: dict | None = None
    atributos: list[ComparacaoAtributo] = field(default_factory=list)
    categoria_diverge: bool = False


@dataclass
class Resultado:
    itens: list[Item]

    def _conta(self, status: str) -> int:
        return sum(1 for i in self.itens if i.status == status)

    @property
    def metricas(self) -> dict[str, Any]:
        tp, fn = self._conta("acerto"), self._conta("faltou")
        fp = self._conta("sobrou") + self._conta("indevido")
        prec = tp / (tp + fp) if tp + fp else 0.0
        cob = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * prec * cob / (prec + cob) if prec + cob else 0.0
        attrs = [a for i in self.itens if i.status == "acerto" for a in i.atributos if not a.fora_do_recorte]
        # entradas que dependem de outra página: completas = achadas e com tudo o que estava fora certo
        dependentes = [i for i in self.itens if i.status in ("acerto", "faltou") and (i.gold or {}).get("fora_do_recorte")]
        completas = sum(1 for i in dependentes if i.status == "acerto"
                        and all(a.bate or a.chave_obtida for a in i.atributos if a.fora_do_recorte))
        return {
            "acertos": tp, "faltaram": fn, "sobraram": self._conta("sobrou"), "indevidos": self._conta("indevido"),
            "precisao": round(prec, 3), "cobertura": round(cob, 3), "f1": round(f1, 3),
            "atributos_corretos": round(sum(a.bate for a in attrs) / len(attrs), 3) if attrs else None,
            "valor_em_outra_chave": round(sum(bool(a.chave_obtida) for a in attrs) / len(attrs), 3) if attrs else None,
            "contexto_recuperado": f"{completas}/{len(dependentes)}" if dependentes else None,
        }

    def como_dict(self) -> dict:
        def item(i: Item) -> dict:
            return {"status": i.status, "nome": i.nome, "gold": i.gold, "saida": i.saida,
                    "categoria_diverge": i.categoria_diverge,
                    "atributos": [a.__dict__ for a in i.atributos]}
        return {"metricas": self.metricas, "itens": [item(i) for i in self.itens]}


def _paginas(d: dict) -> set[int]:
    p = d.get("paginas") or []
    return set(range(int(p[0]), int(p[-1]) + 1)) if p else set()


def comparar(gold: list[dict], saida: list[dict], paginas_do_recorte: set[int] | None = None) -> Resultado:
    entradas = [g for g in gold if g.get("tipo", "entrada") == "entrada"]
    opcionais = {norm(g["nome"]) for g in gold if g.get("tipo") == "opcional"}
    negativas: set[int] = set().union(*[_paginas(g) for g in gold if g.get("tipo") == "negativo"] or [set()])
    if paginas_do_recorte is None:
        paginas_do_recorte = set().union(*[_paginas(g) for g in gold] or [set()])

    usados: set[int] = set()
    itens: list[Item] = []
    por_nome: dict[str, list[int]] = {}
    for i, s in enumerate(saida):
        por_nome.setdefault(norm(s.get("nome", "")), []).append(i)

    for g in entradas:
        candidatos = [i for i in por_nome.get(norm(g["nome"]), []) if i not in usados]
        if not candidatos:
            itens.append(Item("faltou", g["nome"], gold=g))
            continue
        # prefere a mesma categoria canônica quando há homônimos
        mesma = [i for i in candidatos if saida[i].get("categoria_canonica") == g.get("categoria_canonica")]
        escolhido = (mesma or candidatos)[0]
        usados.add(escolhido)
        s = saida[escolhido]
        obtidos = {chave_canonica(k): v for k, v in (s.get("atributos") or {}).items()}
        obtidos.update({k: v for k, v in (s.get("atributos") or {}).items()})
        fora = set(g.get("fora_do_recorte") or [])
        brutos = s.get("atributos") or {}
        attrs = []
        for k, v in (g.get("atributos") or {}).items():
            obtido = obtidos.get(k, obtidos.get(chave_canonica(k)))
            a = ComparacaoAtributo(k, v, obtido, valores_batem(v, obtido), k in fora)
            if not a.bate and not isinstance(v, bool):
                # o valor está lá, só que com outro nome? (ex.: 'tipo' em vez de 'tipo_dano')
                outra = next((ko for ko, vo in brutos.items() if ko != k and valores_batem(v, vo)), None)
                if outra:
                    a.chave_obtida, a.obtido = outra, brutos[outra]
            attrs.append(a)
        itens.append(Item("acerto", g["nome"], gold=g, saida=s, atributos=attrs,
                          categoria_diverge=s.get("categoria_canonica") not in (None, g.get("categoria_canonica"))))

    for i, s in enumerate(saida):
        if i in usados:
            continue
        pags = _paginas(s)
        if norm(s.get("nome", "")) in opcionais:
            status = "opcional"
        elif pags and pags <= negativas:
            status = "indevido"
        elif pags and not (pags & paginas_do_recorte):
            status = "fora"
        else:
            status = "sobrou"
        itens.append(Item(status, s.get("nome", "?"), saida=s))
    return Resultado(itens)


def verificar_no_texto(entrada: dict, texto_das_paginas: str) -> dict:
    """Para revisar o gold: quais valores aparecem literalmente no texto da página.

    True = encontrado, False = não encontrado (conferir!), None = não dá para verificar.
    """
    texto = norm(texto_das_paginas)
    texto_junto = texto.replace(" ", "")

    def achou(v: Any):
        if isinstance(v, bool) or v is None:
            return None
        if isinstance(v, list):
            r = [achou(x) for x in v]
            return None if all(x is None for x in r) else all(x is not False for x in r)
        n = norm(v)
        if not n or len(n) < 2 and not n.isdigit():
            return None
        return any(x in texto or x.replace(" ", "") in texto_junto for x in variantes(n))

    return {
        "nome": achou(entrada.get("nome")) if entrada.get("tipo", "entrada") == "entrada" else None,
        "atributos": {k: achou(v) for k, v in (entrada.get("atributos") or {}).items()},
        "descricao_contem": [achou(c) for c in entrada.get("descricao_contem") or []],
        "trecho": achou(entrada.get("trecho", "").split(" / ")[0]) if entrada.get("tipo") == "negativo" else None,
    }
