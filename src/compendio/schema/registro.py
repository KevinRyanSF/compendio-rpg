"""Categorias e atributos dinâmicos, descobertos por sistema.

Uma `Categoria` descreve um tipo de conteúdo de um sistema — por exemplo, os
rituais do Ordem Paranormal — com a lista de atributos que cada entrada tem
(nome do ritual, elemento, círculo, alcance, duração, dados...).

A partir dela gera-se, em tempo de execução:
  * um modelo Pydantic que valida cada entrada (`modelo_entrada`);
  * o JSON Schema que vai para a Claude API como formato de saída
    (`modelo_lote`, com campos para o agente pedir mais contexto);
  * as colunas da view SQL da categoria (em `storage.banco`).

Nada aqui é escrito à mão por sistema: o agente descobre a categoria, o banco
guarda, e tudo o mais é derivado.
"""

from __future__ import annotations

import re
from typing import Annotated, Any, Literal, Optional

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, create_model, field_validator

from .. import dados as dados_mod
from . import canonico

TipoAtributo = Literal["texto", "inteiro", "numero", "booleano", "dados", "lista"]

# campos que toda entrada tem e que viram colunas fixas da tabela `entradas`
CAMPOS_BASE = ("nome", "descricao")
RESERVADOS = set(CAMPOS_BASE) | {"id", "categoria_id", "slug", "valores", "livro_id", "pagina_inicio",
                                 "pagina_fim", "chunk_id", "confianca", "criado_em", "atualizado_em"}


def _validar_dados(valor: str | None) -> str | None:
    if valor is None or str(valor).strip() in ("", "-", "–", "—"):
        return None
    if re.fullmatch(r"\s*\d+\s*", str(valor)):  # dano fixo (ex.: zarabatana causa 1)
        return str(valor).strip()
    expressoes = dados_mod.extrair(str(valor))
    if not expressoes:
        raise ValueError(f"esperava uma expressão de dados (ex.: 2d6+3), veio {valor!r}")
    return str(valor).strip()


_TIPOS_PY: dict[str, Any] = {
    "texto": str,
    "inteiro": int,
    "numero": float,
    "booleano": bool,
    "dados": Annotated[str, AfterValidator(_validar_dados)],
    "lista": list[str],
}


class Atributo(BaseModel):
    nome: str = Field(description="identificador em snake_case, ex.: 'tempo_de_conjuracao'")
    rotulo: str = Field(description="como o livro escreve, ex.: 'Tempo de Conjuração'")
    tipo: TipoAtributo = "texto"
    descricao: str = ""
    canonico: Optional[str] = Field(default=None, description="chave da camada canônica, ex.: 'execucao'")
    obrigatorio: bool = False

    @field_validator("nome")
    @classmethod
    def _nome_seguro(cls, v: str) -> str:
        s = canonico.slug(v)
        return f"attr_{s}" if s in RESERVADOS else s

    @field_validator("canonico")
    @classmethod
    def _canonico_existe(cls, v: str | None) -> str | None:
        if v is not None and v not in canonico.ATRIBUTOS:
            return None  # o LLM inventou uma chave: fica sem mapeamento em vez de quebrar
        return v

    def model_post_init(self, _ctx) -> None:
        if self.canonico is None:
            self.canonico = canonico.atributo_por_termo(self.rotulo) or canonico.atributo_por_termo(self.nome)


class Categoria(BaseModel):
    sistema: str
    nome: str = Field(description="como o livro chama, ex.: 'Ritual'")
    canonica: str = Field(description="uma das categorias canônicas")
    descricao: str = ""
    atributos: list[Atributo] = Field(default_factory=list)
    versao: int = 1

    @property
    def slug(self) -> str:
        return canonico.slug(self.nome)

    @field_validator("canonica")
    @classmethod
    def _canonica_existe(cls, v: str) -> str:
        if v not in canonico.CATEGORIAS:
            v2 = canonico.categoria_por_termo(v)
            if not v2:
                raise ValueError(f"categoria canônica desconhecida: {v!r} (use uma de {list(canonico.CATEGORIAS)})")
            return v2
        return v

    def atributo(self, nome: str) -> Atributo | None:
        return next((a for a in self.atributos if a.nome == nome), None)

    def mesclar(self, outra: "Categoria") -> tuple["Categoria", list[str]]:
        """Une os atributos (os existentes mandam). Devolve a nova categoria e os nomes adicionados."""
        atuais = {a.nome for a in self.atributos}
        novos = [a for a in outra.atributos if a.nome not in atuais]
        if not novos:
            return self, []
        return (
            self.model_copy(update={"atributos": [*self.atributos, *novos], "versao": self.versao + 1}),
            [a.nome for a in novos],
        )


def modelo_entrada(categoria: Categoria) -> type[BaseModel]:
    """Modelo Pydantic de uma entrada da categoria. Campos extras são aceitos e
    reportados — é assim que atributos novos aparecem durante a extração."""
    campos: dict[str, Any] = {
        "nome": (str, Field(description=f"nome do(a) {categoria.nome.lower()} como está no livro")),
        "descricao": (str, Field(default="", description="texto de regras/efeito, resumido sem perder mecânica")),
    }
    for a in categoria.atributos:
        tipo = _TIPOS_PY[a.tipo]
        desc = a.rotulo + (f" — {a.descricao}" if a.descricao else "")
        if a.obrigatorio:
            campos[a.nome] = (tipo, Field(description=desc))
        else:
            campos[a.nome] = (Optional[tipo], Field(default=None, description=desc))
    return create_model(
        f"Entrada_{categoria.slug}",
        __config__=ConfigDict(extra="allow"),
        **campos,
    )


def modelo_lote(categoria: Categoria) -> type[BaseModel]:
    """O que um especialista devolve por trecho: as entradas encontradas e,
    se faltar contexto, o que ele precisa buscar (gancho do passo agentivo)."""
    Entrada = modelo_entrada(categoria)
    return create_model(
        f"Lote_{categoria.slug}",
        entradas=(list[Entrada], Field(default_factory=list)),
        incompletas=(list[str], Field(default_factory=list,
                     description="nomes de entradas que começam ou terminam fora deste trecho")),
        contexto_insuficiente=(bool, Field(default=False)),
        buscar=(list[str], Field(default_factory=list,
                description="termos/títulos a buscar no livro para completar as entradas")),
    )


def atributos_extras(entrada: BaseModel) -> dict[str, Any]:
    return dict(entrada.model_extra or {})
