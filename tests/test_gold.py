"""O gold set precisa estar bem formado: é a régua de todos os experimentos."""
import json
from pathlib import Path

import pytest

from compendio.schema import canonico

GOLD = Path(__file__).parent.parent / "gold"
RECORTES = json.loads((GOLD / "recortes.json").read_text(encoding="utf-8"))
LIVROS = list(RECORTES["livros"].items())


def linhas(arquivo):
    return [json.loads(l) for l in (GOLD / arquivo).read_text(encoding="utf-8").splitlines() if l.strip()]


@pytest.mark.parametrize("chave,livro", LIVROS)
def test_linhas_bem_formadas(chave, livro):
    paginas_do_recorte = set()
    for r in livro["recortes"]:
        paginas_do_recorte |= set(range(r["paginas"][0], r["paginas"][1] + 1))
    for d in linhas(livro["gold"]):
        assert d["tipo"] in {"entrada", "opcional", "negativo"}
        assert d["sistema"] == livro["sistema"]
        ini, fim = d["paginas"]
        assert ini <= fim
        # toda linha toca alguma página do recorte
        assert paginas_do_recorte & set(range(ini, fim + 1)), d
        if d["tipo"] == "entrada":
            assert d["nome"].strip()
            assert d["categoria_canonica"] in canonico.CATEGORIAS
            assert d["dificuldade"] in {"normal", "tabela", "variantes", "atravessa_pagina"}
            if d.get("fora_do_recorte"):
                assert d["dificuldade"] == "atravessa_pagina"


@pytest.mark.parametrize("chave,livro", LIVROS)
def test_sem_nomes_duplicados_na_mesma_categoria(chave, livro):
    vistos = set()
    for d in linhas(livro["gold"]):
        if d["tipo"] != "entrada":
            continue
        k = (d["categoria_no_livro"], canonico.normalizar(d["nome"]))
        assert k not in vistos, k
        vistos.add(k)


def test_gold_nao_tem_marca_dagua_nem_email():
    for _, livro in LIVROS:
        assert "@" not in (GOLD / livro["gold"]).read_text(encoding="utf-8")
