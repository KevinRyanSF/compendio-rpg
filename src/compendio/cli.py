"""Linha de comando: `uv run compendio <comando>`.

    verificar [--api]        confere .env e, com --api, faz uma chamada mínima a cada modelo
    indice LIVRO.pdf         mostra o índice compacto (o que o Mapeador vai ler)
    ingerir LIVRO.pdf        gera data/chunks/<livro>.jsonl e o diagnóstico do PDF
    banco                    categorias, atributos e entradas registrados
    demo                     cria um banco de exemplo (ritual x magia) para ver as views
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import config as config_mod


def _abrir_pdf(caminho: str):
    from pdfscope import PdfDocument

    return PdfDocument(caminho)


def cmd_verificar(args) -> int:
    cfg = config_mod.carregar(provedor=args.provedor)
    print(f"provedor:          {cfg.provedor}")
    print(f"{cfg.nome_da_chave + ':':<19}{'ok' if cfg.api_key else 'FALTANDO (copie .env.example para .env)'}")
    print(f"modelo rápido:     {cfg.modelo_rapido}")
    print(f"modelo forte:      {cfg.modelo_forte}")
    print(f"banco:             {cfg.banco}")
    try:
        import pdfscope

        print(f"pdfscope:          {pdfscope.__version__}")
    except ImportError:
        print("pdfscope:          NÃO INSTALADO (rode `uv sync`)")
        return 1
    if args.api:
        from .llm import criar_llm

        llm = criar_llm(cfg)
        for modelo in dict.fromkeys([cfg.modelo_rapido, cfg.modelo_forte]):
            r = llm.texto(etapa="verificar", conteudo="Responda só: ok", modelo=modelo)
            print(f"{modelo} respondeu: {r.dados['texto'].strip()!r}  ({r.uso.entrada}+{r.uso.saida} tokens)")
    return 0 if cfg.api_key else 1


def cmd_indice(args) -> int:
    from .ingest import resumo_do_indice

    with _abrir_pdf(args.livro) as doc:
        texto = resumo_do_indice(doc)
    print(texto)
    print(f"\n~{len(texto) // 4} tokens para o Mapeador ler o índice inteiro")
    return 0


def cmd_ingerir(args) -> int:
    from .ingest import chunks_por_indice, diagnostico, salvar_jsonl

    with _abrir_pdf(args.livro) as doc:
        chunks = chunks_por_indice(doc, max_chars=args.max_chars)
        diag = diagnostico(doc, chunks)
    saida = Path(args.saida or f"data/chunks/{Path(args.livro).stem}.jsonl")
    salvar_jsonl(chunks, saida)
    print(json.dumps(diag, ensure_ascii=False, indent=2))
    print(f"\n{len(chunks)} chunks salvos em {saida}")
    if not diag["entradas_no_indice"]:
        print("ATENÇÃO: o PDF não tem índice — os chunks foram feitos por janelas de páginas.")
    return 0


def cmd_banco(args) -> int:
    from .storage import Banco

    cfg = config_mod.carregar()
    with Banco(args.banco or cfg.banco) as b:
        linhas = b.contagem()
        if not linhas:
            print("banco vazio")
        for r in linhas:
            print(f"{r['sistema']:<20} {r['categoria']:<20} [{r['canonica']}] v{r['versao']} "
                  f"{r['atributos']} atributos, {r['entradas']} entradas")
    return 0


def cmd_demo(args) -> int:
    from .exemplo import popular_exemplo
    from .storage import Banco

    caminho = Path(args.banco or "data/demo.db")
    if caminho.exists():
        caminho.unlink()
    with Banco(caminho) as b:
        popular_exemplo(b)
        for cat in b.categorias():
            print(f"\n== {b.nome_da_view(cat)} ==")
            for e in b.entradas(cat.sistema, cat.slug):
                print({k: v for k, v in e.items() if v is not None})
        print("\n== por_canonica('efeito_sobrenatural') ==")
        for e in b.por_canonica("efeito_sobrenatural"):
            print(e)
    print(f"\nbanco de exemplo em {caminho} (abra no DB Browser for SQLite e veja as views)")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="compendio")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("verificar")
    s.add_argument("--api", action="store_true", help="faz uma chamada mínima a cada modelo")
    s.add_argument("--provedor", choices=["gemini", "claude"], help="sobrescreve COMPENDIO_PROVEDOR")
    s.set_defaults(f=cmd_verificar)

    s = sub.add_parser("indice")
    s.add_argument("livro")
    s.set_defaults(f=cmd_indice)

    s = sub.add_parser("ingerir")
    s.add_argument("livro")
    s.add_argument("--max-chars", type=int, default=12_000)
    s.add_argument("--saida")
    s.set_defaults(f=cmd_ingerir)

    s = sub.add_parser("banco")
    s.add_argument("--banco")
    s.set_defaults(f=cmd_banco)

    s = sub.add_parser("demo")
    s.add_argument("--banco")
    s.set_defaults(f=cmd_demo)

    args = p.parse_args(argv)
    return args.f(args)


if __name__ == "__main__":
    sys.exit(main())
