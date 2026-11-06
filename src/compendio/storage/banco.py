"""Compêndio em SQLite, com esquema que cresce conforme o sistema é descoberto.

Tabelas fixas (não mudam nunca):
    sistemas, livros, categorias, atributos, termos, entradas

Os atributos de cada entrada ficam em `entradas.valores` (JSON). Para cada
categoria registrada o banco (re)cria uma VIEW com uma coluna por atributo:

    SELECT nome, circulo, alcance, duracao, dados FROM "v_ordem_paranormal__ritual";

Assim o VTT consulta como se fosse uma tabela comum, e um atributo novo
descoberto no meio da extração não exige migração — só recriar a view.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..schema import canonico
from ..schema.registro import Atributo, Categoria, atributos_extras, modelo_entrada

_DDL = """
CREATE TABLE IF NOT EXISTS sistemas (
    id INTEGER PRIMARY KEY,
    nome TEXT NOT NULL UNIQUE,
    slug TEXT NOT NULL UNIQUE,
    criado_em TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS livros (
    id INTEGER PRIMARY KEY,
    sistema_id INTEGER NOT NULL REFERENCES sistemas(id),
    titulo TEXT NOT NULL,
    paginas INTEGER,
    UNIQUE (sistema_id, titulo)
);
CREATE TABLE IF NOT EXISTS categorias (
    id INTEGER PRIMARY KEY,
    sistema_id INTEGER NOT NULL REFERENCES sistemas(id),
    slug TEXT NOT NULL,
    nome TEXT NOT NULL,
    canonica TEXT NOT NULL,
    descricao TEXT NOT NULL DEFAULT '',
    versao INTEGER NOT NULL DEFAULT 1,
    UNIQUE (sistema_id, slug)
);
CREATE TABLE IF NOT EXISTS atributos (
    id INTEGER PRIMARY KEY,
    categoria_id INTEGER NOT NULL REFERENCES categorias(id) ON DELETE CASCADE,
    ordem INTEGER NOT NULL,
    nome TEXT NOT NULL,
    rotulo TEXT NOT NULL,
    tipo TEXT NOT NULL,
    descricao TEXT NOT NULL DEFAULT '',
    canonico TEXT,
    obrigatorio INTEGER NOT NULL DEFAULT 0,
    UNIQUE (categoria_id, nome)
);
CREATE TABLE IF NOT EXISTS termos (
    sistema_id INTEGER NOT NULL REFERENCES sistemas(id),
    termo TEXT NOT NULL,
    tipo TEXT NOT NULL CHECK (tipo IN ('categoria', 'atributo')),
    canonico TEXT NOT NULL,
    PRIMARY KEY (sistema_id, termo, tipo)
);
CREATE TABLE IF NOT EXISTS entradas (
    id INTEGER PRIMARY KEY,
    categoria_id INTEGER NOT NULL REFERENCES categorias(id),
    slug TEXT NOT NULL,
    nome TEXT NOT NULL,
    descricao TEXT NOT NULL DEFAULT '',
    valores TEXT NOT NULL DEFAULT '{}',
    livro_id INTEGER REFERENCES livros(id),
    pagina_inicio INTEGER,
    pagina_fim INTEGER,
    chunk_id TEXT,
    confianca REAL,
    criado_em TEXT NOT NULL,
    atualizado_em TEXT NOT NULL,
    UNIQUE (categoria_id, slug)
);
"""


def _agora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _q(ident: str) -> str:
    """Identificador SQL entre aspas (os slugs já são [a-z0-9_], isto é só cinto e suspensório)."""
    return '"' + ident.replace('"', "") + '"'


class Banco:
    def __init__(self, caminho: str | Path = ":memory:"):
        if str(caminho) != ":memory:":
            Path(caminho).parent.mkdir(parents=True, exist_ok=True)
        self.con = sqlite3.connect(str(caminho))
        self.con.row_factory = sqlite3.Row
        self.con.execute("PRAGMA foreign_keys = ON")
        self.con.executescript(_DDL)

    def __enter__(self) -> "Banco":
        return self

    def __exit__(self, *exc) -> None:
        self.fechar()

    def fechar(self) -> None:
        self.con.commit()
        self.con.close()

    # ---------------------------------------------------------------- sistemas

    def sistema_id(self, nome: str) -> int:
        slug = canonico.slug(nome)
        linha = self.con.execute("SELECT id FROM sistemas WHERE slug = ?", (slug,)).fetchone()
        if linha:
            return linha["id"]
        cur = self.con.execute(
            "INSERT INTO sistemas (nome, slug, criado_em) VALUES (?, ?, ?)", (nome, slug, _agora())
        )
        return cur.lastrowid

    def livro_id(self, sistema: str, titulo: str, paginas: int | None = None) -> int:
        sid = self.sistema_id(sistema)
        self.con.execute(
            "INSERT OR IGNORE INTO livros (sistema_id, titulo, paginas) VALUES (?, ?, ?)", (sid, titulo, paginas)
        )
        return self.con.execute(
            "SELECT id FROM livros WHERE sistema_id = ? AND titulo = ?", (sid, titulo)
        ).fetchone()["id"]

    # -------------------------------------------------------------- glossário

    def registrar_termo(self, sistema: str, termo: str, canonico_: str, tipo: str = "categoria") -> None:
        self.con.execute(
            "INSERT OR REPLACE INTO termos (sistema_id, termo, tipo, canonico) VALUES (?, ?, ?, ?)",
            (self.sistema_id(sistema), canonico.normalizar(termo), tipo, canonico_),
        )

    def glossario(self, sistema: str) -> dict[str, dict[str, str]]:
        sid = self.sistema_id(sistema)
        saida: dict[str, dict[str, str]] = {"categoria": {}, "atributo": {}}
        for r in self.con.execute("SELECT termo, tipo, canonico FROM termos WHERE sistema_id = ?", (sid,)):
            saida[r["tipo"]][r["termo"]] = r["canonico"]
        return saida

    # ------------------------------------------------------------- categorias

    def registrar_categoria(self, categoria: Categoria) -> tuple[Categoria, list[str]]:
        """Cria ou amplia a categoria. Devolve a versão gravada e os atributos novos."""
        existente = self.categoria(categoria.sistema, categoria.slug)
        if existente:
            final, novos = existente.mesclar(categoria)
            if not novos:
                return existente, []
        else:
            final, novos = categoria, [a.nome for a in categoria.atributos]

        sid = self.sistema_id(final.sistema)
        with self.con:
            self.con.execute(
                """INSERT INTO categorias (sistema_id, slug, nome, canonica, descricao, versao)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT (sistema_id, slug) DO UPDATE SET versao = excluded.versao""",
                (sid, final.slug, final.nome, final.canonica, final.descricao, final.versao),
            )
            cid = self._categoria_id(final.sistema, final.slug)
            for ordem, a in enumerate(final.atributos):
                self.con.execute(
                    """INSERT OR IGNORE INTO atributos
                       (categoria_id, ordem, nome, rotulo, tipo, descricao, canonico, obrigatorio)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (cid, ordem, a.nome, a.rotulo, a.tipo, a.descricao, a.canonico, int(a.obrigatorio)),
                )
            self.registrar_termo(final.sistema, final.nome, final.canonica, "categoria")
            for a in final.atributos:
                if a.canonico:
                    self.registrar_termo(final.sistema, a.rotulo, a.canonico, "atributo")
            self._recriar_view(final, cid)
        return final, novos

    def _categoria_id(self, sistema: str, slug: str) -> int | None:
        linha = self.con.execute(
            "SELECT c.id FROM categorias c JOIN sistemas s ON s.id = c.sistema_id WHERE s.slug = ? AND c.slug = ?",
            (canonico.slug(sistema), slug),
        ).fetchone()
        return linha["id"] if linha else None

    def categoria(self, sistema: str, slug: str) -> Categoria | None:
        linha = self.con.execute(
            """SELECT c.*, s.nome AS sistema FROM categorias c JOIN sistemas s ON s.id = c.sistema_id
               WHERE s.slug = ? AND c.slug = ?""",
            (canonico.slug(sistema), canonico.slug(slug)),
        ).fetchone()
        if not linha:
            return None
        attrs = [
            Atributo(nome=r["nome"], rotulo=r["rotulo"], tipo=r["tipo"], descricao=r["descricao"],
                     canonico=r["canonico"], obrigatorio=bool(r["obrigatorio"]))
            for r in self.con.execute(
                "SELECT * FROM atributos WHERE categoria_id = ? ORDER BY ordem", (linha["id"],)
            )
        ]
        return Categoria(sistema=linha["sistema"], nome=linha["nome"], canonica=linha["canonica"],
                         descricao=linha["descricao"], atributos=attrs, versao=linha["versao"])

    def categorias(self, sistema: str | None = None) -> list[Categoria]:
        sql = "SELECT s.nome AS sistema, c.slug FROM categorias c JOIN sistemas s ON s.id = c.sistema_id"
        args: tuple = ()
        if sistema:
            sql += " WHERE s.slug = ?"
            args = (canonico.slug(sistema),)
        return [self.categoria(r["sistema"], r["slug"]) for r in self.con.execute(sql + " ORDER BY s.nome, c.slug", args)]

    @staticmethod
    def nome_da_view(categoria: Categoria) -> str:
        return f"v_{canonico.slug(categoria.sistema)}__{categoria.slug}"

    def _recriar_view(self, categoria: Categoria, cid: int) -> None:
        view = self.nome_da_view(categoria)
        colunas = ",\n  ".join(
            f"json_extract(e.valores, '$.{a.nome}') AS {_q(a.nome)}" for a in categoria.atributos
        )
        self.con.execute(f"DROP VIEW IF EXISTS {_q(view)}")
        self.con.execute(
            f"""CREATE VIEW {_q(view)} AS SELECT
  e.id, e.nome, e.descricao{',' if colunas else ''}
  {colunas}{',' if colunas else ''}
  e.pagina_inicio, e.pagina_fim, e.confianca
FROM entradas e WHERE e.categoria_id = {int(cid)}"""
        )

    # --------------------------------------------------------------- entradas

    def salvar_entrada(
        self,
        sistema: str,
        categoria_slug: str,
        valores: dict[str, Any],
        *,
        livro: str | None = None,
        paginas: tuple[int, int] | None = None,
        chunk_id: str | None = None,
        confianca: float | None = None,
        aceitar_novos_atributos: bool = True,
    ) -> int:
        """Valida contra o esquema da categoria e grava (ou mescla, se já existe).

        Atributos que o esquema ainda não conhece entram na categoria como `texto`
        quando `aceitar_novos_atributos` — o esquema cresce com o livro.
        """
        cat = self.categoria(sistema, categoria_slug)
        if cat is None:
            raise KeyError(f"categoria {categoria_slug!r} não registrada para {sistema!r}")

        entrada = modelo_entrada(cat).model_validate(valores)
        brutos = {k: v for k, v in atributos_extras(entrada).items() if v not in (None, "", [])}
        extras: dict[str, Any] = {}
        if brutos:
            if not aceitar_novos_atributos:
                raise ValueError(f"atributos fora do esquema: {sorted(brutos)}")
            novos = [
                Atributo(nome=k, rotulo=k.replace("_", " ").capitalize() if k == canonico.slug(k) else k)
                for k in brutos
            ]
            extras = {a.nome: v for a, v in zip(novos, brutos.values())}
            cat, _ = self.registrar_categoria(cat.model_copy(update={"atributos": novos}))

        conhecidos = {a.nome for a in cat.atributos}
        dump = entrada.model_dump()
        atributos = {k: v for k, v in {**dump, **extras}.items() if k in conhecidos and v is not None}

        cid = self._categoria_id(sistema, cat.slug)
        slug = canonico.slug(entrada.nome)
        livro_id = self.livro_id(sistema, livro) if livro else None
        agora = _agora()

        atual = self.con.execute(
            "SELECT id, valores, descricao FROM entradas WHERE categoria_id = ? AND slug = ?", (cid, slug)
        ).fetchone()
        with self.con:
            if atual:
                # mesma entrada vista de novo (ex.: em dois trechos): completa o que faltava
                mesclado = {**atributos, **json.loads(atual["valores"])}
                descricao = atual["descricao"] if len(atual["descricao"]) >= len(entrada.descricao) else entrada.descricao
                self.con.execute(
                    "UPDATE entradas SET valores = ?, descricao = ?, atualizado_em = ? WHERE id = ?",
                    (json.dumps(mesclado, ensure_ascii=False), descricao, agora, atual["id"]),
                )
                return atual["id"]
            cur = self.con.execute(
                """INSERT INTO entradas (categoria_id, slug, nome, descricao, valores, livro_id,
                                         pagina_inicio, pagina_fim, chunk_id, confianca, criado_em, atualizado_em)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (cid, slug, entrada.nome, entrada.descricao, json.dumps(atributos, ensure_ascii=False), livro_id,
                 paginas[0] if paginas else None, paginas[1] if paginas else None, chunk_id, confianca, agora, agora),
            )
            return cur.lastrowid

    def entradas(self, sistema: str, categoria_slug: str) -> list[dict[str, Any]]:
        cat = self.categoria(sistema, categoria_slug)
        if cat is None:
            return []
        listas = {a.nome for a in cat.atributos if a.tipo == "lista"}
        booleanos = {a.nome for a in cat.atributos if a.tipo == "booleano"}
        saida = []
        for r in self.con.execute(f"SELECT * FROM {_q(self.nome_da_view(cat))} ORDER BY nome"):
            e = dict(r)
            for k in listas:
                if isinstance(e.get(k), str):
                    e[k] = json.loads(e[k])
            for k in booleanos:
                if e.get(k) is not None:
                    e[k] = bool(e[k])
            saida.append(e)
        return saida

    def por_canonica(self, canonica: str) -> list[dict[str, Any]]:
        """Entradas de todos os sistemas numa categoria canônica, com atributos
        renomeados para as chaves canônicas — magias do D&D e rituais do Ordem lado a lado."""
        saida: list[dict[str, Any]] = []
        for cat in self.categorias():
            if cat.canonica != canonica:
                continue
            mapa = {a.nome: a.canonico for a in cat.atributos if a.canonico}
            for e in self.entradas(cat.sistema, cat.slug):
                item = {"sistema": cat.sistema, "categoria": cat.nome, "nome": e["nome"], "descricao": e["descricao"]}
                item.update({mapa[k]: v for k, v in e.items() if k in mapa and v is not None})
                saida.append(item)
        return saida

    def contagem(self) -> list[dict[str, Any]]:
        return [dict(r) for r in self.con.execute(
            """SELECT s.nome AS sistema, c.nome AS categoria, c.canonica, c.versao,
                      (SELECT COUNT(*) FROM atributos a WHERE a.categoria_id = c.id) AS atributos,
                      (SELECT COUNT(*) FROM entradas e WHERE e.categoria_id = c.id) AS entradas
               FROM categorias c JOIN sistemas s ON s.id = c.sistema_id ORDER BY s.nome, c.nome"""
        )]
