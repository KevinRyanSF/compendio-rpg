"""Rodar uma estratégia de extração nos recortes do gold set, avaliar e registrar.

    uv run compendio extrair --livro ordem-paranormal            # baseline, Gemini rápido
    uv run compendio extrair --livro todos --modelo forte
    uv run compendio avaliar --livro ordem-paranormal --saida data/saidas/baseline-gemini-ordem-paranormal.jsonl

Saídas (com texto dos livros) ficam em data/saidas/, fora do git. As métricas, que
não têm conteúdo dos livros, vão para resultados/resultados.csv — essa tabela
é a evidência do relatório.
"""

from __future__ import annotations

import csv
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from . import avaliacao, baseline
from .config import Config
from .llm import LLM, criar_llm
from .revisor import Projeto, _abrir_pdf_padrao

ESTRATEGIAS = {"baseline": baseline.extrair}

COLUNAS = ["data", "livro", "estrategia", "provedor", "modelos", "paginas", "chamadas", "tokens_entrada",
           "tokens_saida", "cache_lido", "segundos", "acertos", "faltaram", "sobraram", "indevidos",
           "precisao", "cobertura", "f1", "atributos_corretos", "contexto_recuperado", "saida"]


def resolver_modelo(cfg: Config, papel: str) -> str:
    return {"rapido": cfg.modelo_rapido, "forte": cfg.modelo_forte}.get(papel, papel)


def rodar(raiz: Path, livro: str, cfg: Config, *, estrategia: str = "baseline", papel: str = "rapido",
          llm: LLM | None = None, abrir_pdf: Callable = _abrir_pdf_padrao,
          ao_progresso: Callable[[int, int, int], None] | None = None) -> tuple[Path, dict]:
    projeto = Projeto(raiz, abrir_pdf)
    info = projeto.livro(livro)
    paginas = {p: projeto.texto(livro, p) for p in sorted(projeto.paginas_do_recorte(livro))}
    llm = llm or criar_llm(cfg)
    inicio, ja = time.perf_counter(), len(llm.registro.chamadas)

    entradas = ESTRATEGIAS[estrategia](llm, paginas, sistema=info["sistema"],
                                       modelo=resolver_modelo(cfg, papel), ao_progresso=ao_progresso)

    nome = f"{estrategia}-{cfg.provedor}-{papel}-{livro}"
    saida = raiz / "data" / "saidas" / f"{nome}.jsonl"
    saida.parent.mkdir(parents=True, exist_ok=True)
    avaliacao.salvar_jsonl(entradas, saida)

    usos = llm.registro.chamadas[ja:]
    meta = {
        "data": datetime.now().isoformat(timespec="seconds"), "livro": livro, "estrategia": estrategia,
        "provedor": cfg.provedor, "modelos": ",".join(sorted({u.modelo for u in usos})), "paginas": len(paginas),
        "chamadas": len(usos), "tokens_entrada": sum(u.entrada + u.cache_criado for u in usos),
        "tokens_saida": sum(u.saida for u in usos), "cache_lido": sum(u.cache_lido for u in usos),
        "segundos": round(time.perf_counter() - inicio, 1),
    }
    saida.with_suffix(".meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return saida, meta


def avaliar(raiz: Path, livro: str, saida: Path) -> dict:
    projeto = Projeto(raiz)
    rel = str(Path(saida).resolve().relative_to(Path(raiz).resolve())).replace("\\", "/")
    return projeto.comparar(livro, rel)["metricas"]


def registrar(raiz: Path, meta: dict, metricas: dict, saida: Path) -> Path:
    arquivo = raiz / "resultados" / "resultados.csv"
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    novo = not arquivo.exists()
    linha: dict[str, Any] = {**meta, **metricas,
                             "saida": str(Path(saida).resolve().relative_to(Path(raiz).resolve())).replace("\\", "/")}
    with arquivo.open("a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUNAS, extrasaction="ignore")
        if novo:
            w.writeheader()
        w.writerow(linha)
    return arquivo


def formatar(meta: dict, m: dict) -> str:
    pct = lambda v: "—" if v is None else f"{v * 100:.0f}%"  # noqa: E731
    return (f"{meta['livro']} · {meta['estrategia']} · {meta['provedor']} ({meta['modelos']})\n"
            f"  precisão {pct(m['precisao'])} · cobertura {pct(m['cobertura'])} · F1 {pct(m['f1'])} · "
            f"atributos corretos {pct(m['atributos_corretos'])} · contexto recuperado {m['contexto_recuperado'] or '—'}\n"
            f"  {m['acertos']} acertos, {m['faltaram']} faltaram, {m['sobraram']} sobraram, {m['indevidos']} indevidos\n"
            f"  {meta['chamadas']} chamadas · {meta['tokens_entrada']} tokens de entrada · "
            f"{meta['tokens_saida']} de saída · {meta['segundos']}s")
