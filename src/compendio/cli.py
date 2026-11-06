"""Linha de comando: `uv run compendio <comando>`.

    verificar [--api]        confere .env e, com --api, faz uma chamada mínima a cada modelo
    indice LIVRO.pdf         mostra o índice compacto (o que o Mapeador vai ler)
    ingerir LIVRO.pdf        gera data/chunks/<livro>.jsonl e o diagnóstico do PDF
    banco                    categorias, atributos e entradas registrados
    demo                     cria um banco de exemplo (ritual x magia) para ver as views
    revisar                  revisor visual do gabarito e das saídas (abre no navegador)
    extrair [--livro X]      roda o baseline (ou outra estratégia) nos recortes e avalia
    avaliar --livro --saida  compara uma saída com o gold set
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
        import dataclasses

        from .llm import criar_llm

        # no teste, espera pouco e não repete: o objetivo é só saber se cada modelo responde
        llm = criar_llm(dataclasses.replace(cfg, timeout_s=args.timeout), max_tentativas=1)
        falhas = 0
        for papel, modelo in (("rápido", cfg.modelo_rapido), ("forte", cfg.modelo_forte)):
            print(f"testando {papel} ({modelo})... ", end="", flush=True)
            try:
                r = llm.texto(etapa="verificar", conteudo="Responda só: ok", modelo=modelo, max_tokens=1024)
                reserva = f" [respondeu o reserva {r.uso.modelo}]" if r.uso.modelo != modelo.split(",")[0] else ""
                print(f"ok — {r.dados['texto'].strip()!r} em {r.uso.segundos:.1f}s "
                      f"({r.uso.entrada}+{r.uso.saida} tokens){reserva}")
            except Exception as erro:  # noqa: BLE001
                falhas += 1
                print(f"FALHOU: {type(erro).__name__}: {str(erro)[:300]}")
        if falhas:
            print("\nSe um modelo não existe, não está no seu plano ou está lento, troque o nome em "
                  "COMPENDIO_MODELO_RAPIDO / COMPENDIO_MODELO_FORTE no .env.")
            return 1
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


def _livros(raiz: Path, escolha: str) -> list[str]:
    todos = list(json.loads((raiz / "gold" / "recortes.json").read_text(encoding="utf-8"))["livros"])
    if escolha == "todos":
        return todos
    if escolha not in todos:
        raise SystemExit(f"livro desconhecido: {escolha} (use {', '.join(todos)} ou todos)")
    return [escolha]


def cmd_extrair(args) -> int:
    from . import experimento

    raiz = Path.cwd()
    cfg = config_mod.carregar(provedor=args.provedor)
    for livro in _livros(raiz, args.livro):
        print(f"\n{livro}: {args.estrategia} com {cfg.provedor} ({experimento.resolver_modelo(cfg, args.modelo)})")

        def progresso(i, total, n):
            print(f"\r  página {i}/{total} · {n} entradas", end="", flush=True)

        try:
            saida, meta = experimento.rodar(raiz, livro, cfg, estrategia=args.estrategia, papel=args.modelo,
                                            ao_progresso=progresso)
        except Exception as erro:  # noqa: BLE001 - registra e segue para o próximo livro
            print(f"\n  FALHOU: {type(erro).__name__}: {str(erro)[:300]}")
            continue
        print(f"\n  saída: {saida.relative_to(raiz)}")
        if not args.sem_avaliar:
            metricas = experimento.avaliar(raiz, livro, saida)
            experimento.registrar(raiz, meta, metricas, saida)
            print(experimento.formatar(meta, metricas))
    if not args.sem_avaliar:
        print("\nresultados registrados em resultados/resultados.csv — veja os detalhes em `compendio revisar`")
    return 0


def cmd_avaliar(args) -> int:
    from . import experimento

    raiz = Path.cwd()
    saida = Path(args.saida).resolve()
    meta_arq = saida.with_suffix(".meta.json")
    meta = json.loads(meta_arq.read_text(encoding="utf-8")) if meta_arq.exists() else {
        "livro": args.livro, "estrategia": "?", "provedor": "?", "modelos": "?", "chamadas": 0,
        "tokens_entrada": 0, "tokens_saida": 0, "segundos": 0}
    metricas = experimento.avaliar(raiz, args.livro, saida)
    print(experimento.formatar({**meta, "livro": args.livro}, metricas))
    if args.registrar:
        experimento.registrar(raiz, {**meta, "livro": args.livro}, metricas, saida)
    return 0


def cmd_revisar(args) -> int:
    from .revisor import rodar

    rodar(Path.cwd(), porta=args.porta, abrir_navegador=not args.sem_navegador)
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="compendio")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("verificar")
    s.add_argument("--api", action="store_true", help="faz uma chamada mínima a cada modelo")
    s.add_argument("--provedor", choices=["gemini", "claude"], help="sobrescreve COMPENDIO_PROVEDOR")
    s.add_argument("--timeout", type=float, default=45.0, help="segundos de espera por modelo no teste")
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

    s = sub.add_parser("extrair", help="roda uma estratégia de extração nos recortes do gold set e avalia")
    s.add_argument("--livro", default="todos", help="chave em gold/recortes.json, ou 'todos'")
    s.add_argument("--estrategia", default="baseline", choices=["baseline", "esquema"],
                   help="baseline (1 LLM por página) ou esquema (Mapeador descobre o esquema + Especialista)")
    s.add_argument("--provedor", choices=["gemini", "claude"], help="sobrescreve COMPENDIO_PROVEDOR")
    s.add_argument("--modelo", default="rapido", help="rapido, forte ou o nome de um modelo")
    s.add_argument("--sem-avaliar", action="store_true")
    s.set_defaults(f=cmd_extrair)

    s = sub.add_parser("avaliar", help="compara uma saída .jsonl com o gold set")
    s.add_argument("--livro", required=True)
    s.add_argument("--saida", required=True)
    s.add_argument("--registrar", action="store_true", help="adiciona a linha em resultados/resultados.csv")
    s.set_defaults(f=cmd_avaliar)

    s = sub.add_parser("revisar", help="abre o revisor visual do gabarito e das saídas no navegador")
    s.add_argument("--porta", type=int, default=8765)
    s.add_argument("--sem-navegador", action="store_true")
    s.set_defaults(f=cmd_revisar)

    args = p.parse_args(argv)
    return args.f(args)


if __name__ == "__main__":
    sys.exit(main())
