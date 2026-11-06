"""Estratégia "esquema": Mapeador descobre o esquema → Especialista extrai seguindo o esquema.

A primeira rodada do baseline mostrou que detectar entradas não é o problema
(F1 99%): o problema é a ESTRUTURA. Sem um esquema, cada página inventa seus
campos, funde dois campos num só ("SANGUE 2", "1d4 perfurante") e ignora o que
não está na própria linha (o cabeçalho "Armas Marciais" da tabela) ou está na
prosa ("Discente (+3 PE)", "Em Níveis Superiores").

Dois papéis, com responsabilidades e modelos diferentes:

  Mapeador (modelo forte, 1 chamada por recorte)
      lê amostras do trecho e decide QUE TIPOS de conteúdo existem ali e QUAIS
      CAMPOS cada tipo tem, de onde vem cada campo (rótulo, coluna, cabeçalho
      do grupo, linha sem rótulo, prosa) e a que conceito canônico ele
      corresponde. Se não há conteúdo mecânico (lore, prefácio), devolve nada
      — e o especialista nem é chamado.

  Especialista (modelo rápido, 1 chamada por página, como o baseline)
      extrai as entradas preenchendo exatamente os campos do esquema.

O esquema descoberto vira `Categoria` (schema/registro.py) e é gravado no banco:
é o mesmo objeto que cria as views por categoria para o VTT.
"""

from __future__ import annotations

from typing import Any, Callable, Literal, Optional

from pydantic import BaseModel, Field, ValidationError, create_model

from .baseline import estruturado_com_divisao, juntar_mesmo_nome, limpar
from .llm import LLM
from .schema import canonico
from .schema.registro import Atributo, Categoria, TipoAtributo, modelo_entrada

# ------------------------------------------------------------------ Mapeador

Origem = Literal["rotulo", "coluna", "cabecalho", "linha_sem_rotulo", "prosa"]
# aliases no nível do módulo: dentro das classes o nome `canonico` é o campo, não o módulo
ChaveCanonica = Literal[tuple(canonico.ATRIBUTOS)]  # type: ignore[valid-type]
CategoriaCanonica = Literal[tuple(canonico.CATEGORIAS)]  # type: ignore[valid-type]


class AtributoDescoberto(BaseModel):
    nome: str = Field(description="identificador em snake_case sem acento, ex.: tempo_de_conjuracao")
    rotulo: str = Field(description="como o livro escreve o campo; se não houver rótulo, descreva curto")
    tipo: TipoAtributo = Field(description="texto, inteiro, numero, booleano, dados (ex.: 2d6+1) ou lista")
    canonico: Optional[ChaveCanonica] = Field(
        default=None, description="conceito comum entre sistemas a que o campo corresponde, se houver")
    origem: Origem = Field(description="de onde o valor sai: rotulo ('Alcance: curto'), coluna de tabela, "
                                       "cabecalho do grupo da tabela, linha_sem_rotulo ('SANGUE 2'), prosa")
    como_encontrar: str = Field(description="instrução curta para achar e separar o valor")


class CategoriaDescoberta(BaseModel):
    nome: str = Field(description="como o livro chama o tipo de entrada, no singular (Ritual, Magia, Arma, Condição)")
    canonica: CategoriaCanonica
    descricao: str = ""
    como_identificar: str = Field(description="como reconhecer onde começa cada entrada desse tipo")
    atributos: list[AtributoDescoberto] = Field(default_factory=list)


class Esquema(BaseModel):
    categorias: list[CategoriaDescoberta] = Field(default_factory=list)


INSTRUCOES_MAPEADOR = """Você é o Mapeador de um sistema que monta compêndios de livros de RPG.
Sistema: {sistema}.

Leia o trecho e descubra o ESQUEMA do conteúdo mecânico dele: que tipos de entrada existem
(ex.: Ritual, Magia, Arma, Munição, Condição) e quais CAMPOS cada tipo tem. Não extraia as entradas.

Regras:
- Um campo por informação. Se o livro junta duas informações (ex.: "SANGUE 2" = elemento + círculo;
  "1d4 perfurante" = dano + tipo de dano; "3° nível de evocação" = nível + escola), crie DOIS campos
  e explique em `como_encontrar` como separar.
- Inclua campos que não estão na linha da entrada: o cabeçalho do grupo na tabela
  (ex.: "Armas Marciais Corpo-a-Corpo" → grupo e empunhadura) com origem `cabecalho`.
- Inclua campos que ficam na prosa e têm valor de regra: versões aprimoradas
  (ex.: "Discente (+3 PE)", "Verdadeiro (+7 PE)", "Em Níveis Superiores"), dados rolados no efeito,
  teste de resistência, se pode ser conjurada como ritual.
- Use `canonico` quando o campo corresponder a um destes conceitos comuns:
{canonicos}
- Nome, descrição e páginas já existem em toda entrada: não crie campos para eles.
- Se o trecho não tiver conteúdo mecânico (lore, história, prefácio, exemplo de jogo), devolva lista vazia."""


def _lista_canonicos() -> str:
    return "\n".join(f"  {k}: {v}" for k, v in canonico.ATRIBUTOS.items())


def descobrir(llm: LLM, texto: str, *, sistema: str, modelo: str | None = None,
              max_chars: int = 14_000) -> list[Categoria]:
    """Uma chamada ao Mapeador. `texto` é uma amostra do trecho (cortada em `max_chars`)."""
    r = llm.estruturado(etapa="mapeador", instrucoes=INSTRUCOES_MAPEADOR.format(
        sistema=sistema, canonicos=_lista_canonicos()), conteudo=texto[:max_chars], schema=Esquema,
        modelo=modelo, max_tokens=8192)
    categorias = []
    for c in Esquema.model_validate(r.dados).categorias:
        atributos, vistos = [], set()
        for a in c.atributos:
            atributo = Atributo(nome=a.nome, rotulo=limpar(a.rotulo) or a.nome, tipo=a.tipo,
                                canonico=a.canonico, descricao=f"[{a.origem}] {limpar(a.como_encontrar)}")
            if atributo.nome not in vistos:
                vistos.add(atributo.nome)
                atributos.append(atributo)
        categorias.append(Categoria(sistema=sistema, nome=limpar(c.nome), canonica=c.canonica,
                                    descricao=limpar(c.como_identificar or c.descricao), atributos=atributos))
    return categorias


# --------------------------------------------------------------- Especialista

INSTRUCOES_ESPECIALISTA = """Você é o Especialista de extração de um sistema que monta compêndios de livros de RPG.
Sistema: {sistema}.

Extraia da página TODAS as entradas dos tipos abaixo, preenchendo exatamente os campos de cada tipo.
{tipos}

Regras:
- nome exatamente como no livro; descricao = o efeito mecânico em até duas frases.
- Copie os valores do livro sem reescrever, mas SEPARE o que o esquema separa
  (ex.: "SANGUE 2" → elemento "Sangue" e círculo 2).
- Campos de origem `cabecalho`: use o cabeçalho de grupo mais recente acima da linha.
- Campos de origem `prosa`: procure no texto da entrada (ex.: "Discente (+3 PE): ...").
- Campo sem valor no livro: deixe nulo. Não invente.
- Se uma entrada começa ou termina fora da página, extraia o que estiver visível e liste o nome em `incompletas`.
- Escreva em português com acentos normais (sem entidades HTML)."""


def _descrever(cat: Categoria) -> str:
    linhas = [f"\n## {cat.nome} → lista `{cat.slug}`", f"Como identificar: {cat.descricao}"]
    for a in cat.atributos:
        linhas.append(f"- {a.nome} ({a.tipo}): {a.rotulo}. {a.descricao}")
    return "\n".join(linhas)


def _modelo_pagina(categorias: list[Categoria]) -> type[BaseModel]:
    campos: dict[str, Any] = {cat.slug: (list[modelo_entrada(cat)], Field(default_factory=list))
                              for cat in categorias}
    campos["incompletas"] = (list[str], Field(default_factory=list))
    return create_model("Pagina", **campos)


def _valores(cat: Categoria, bruto: dict) -> tuple[dict, list[str]]:
    """Valida a entrada contra o esquema; o que não validar fica como veio e vira aviso."""
    try:
        validado = modelo_entrada(cat).model_validate(bruto).model_dump()
        return validado, []
    except ValidationError as erro:
        return dict(bruto), [f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in erro.errors()]


def para_saida(cat: Categoria, valores: dict, pagina: int, avisos: list[str] | None = None) -> dict:
    """Chaves canônicas quando existem (é o que o VTT consulta); senão o nome do campo no sistema."""
    atributos: dict[str, Any] = {}
    for a in cat.atributos:
        v = valores.get(a.nome)
        if v in (None, "", []):
            continue
        chave = a.canonico if a.canonico and a.canonico not in atributos else a.nome
        atributos[chave] = limpar(v) if isinstance(v, str) else v
    d = {"sistema": cat.sistema, "categoria_canonica": cat.canonica, "categoria_no_livro": cat.nome,
         "nome": limpar(str(valores.get("nome", ""))), "paginas": [pagina, pagina], "atributos": atributos,
         "descricao": limpar(str(valores.get("descricao") or ""))}
    if avisos:
        d["avisos"] = avisos
    return d


def extrair_pagina(llm: LLM, texto: str, pagina: int, categorias: list[Categoria], *, sistema: str,
                   modelo: str | None = None) -> tuple[list[tuple[Categoria, dict]], list[str]]:
    """Devolve [(categoria, valores brutos)] e os nomes marcados como incompletos."""
    instrucoes = INSTRUCOES_ESPECIALISTA.format(sistema=sistema, tipos="".join(_descrever(c) for c in categorias))
    respostas = estruturado_com_divisao(llm, etapa="especialista", instrucoes=instrucoes,
                                        prefixo=f"[Página {pagina}]", texto=texto,
                                        schema=_modelo_pagina(categorias), modelo=modelo)
    achadas, incompletas = [], []
    for d in respostas:
        incompletas += [limpar(n) for n in d.get("incompletas") or []]
        for cat in categorias:
            for bruto in d.get(cat.slug) or []:
                if isinstance(bruto, dict) and str(bruto.get("nome") or "").strip():
                    achadas.append((cat, bruto))
    return achadas, incompletas


# ------------------------------------------------------------------ estratégia

def _blocos(paginas: dict[int, str]) -> list[list[int]]:
    """Páginas consecutivas formam um bloco (= um recorte): o Mapeador roda uma vez por bloco."""
    blocos: list[list[int]] = []
    for p in sorted(paginas):
        if blocos and p == blocos[-1][-1] + 1:
            blocos[-1].append(p)
        else:
            blocos.append([p])
    return blocos


def extrair(llm: LLM, paginas: dict[int, str], *, sistema: str, modelo: str | None = None,
            modelo_mapeador: str | None = None, banco=None,
            ao_progresso: Callable[[int, int, int], None] | None = None) -> list[dict]:
    brutas: list[dict] = []
    feitas = 0
    for bloco in _blocos(paginas):
        amostra = "\n\n".join(f"[Página {p}]\n{paginas[p]}" for p in bloco if paginas[p].strip())
        categorias = descobrir(llm, amostra, sistema=sistema, modelo=modelo_mapeador) if amostra else []
        if banco is not None:
            categorias = [banco.registrar_categoria(c)[0] for c in categorias]
        for p in bloco:
            feitas += 1
            if categorias and paginas[p].strip():
                achadas, _ = extrair_pagina(llm, paginas[p], p, categorias, sistema=sistema, modelo=modelo)
                for cat, bruto in achadas:
                    valores, avisos = _valores(cat, bruto)
                    brutas.append(para_saida(cat, valores, p, avisos))
                    if banco is not None and not avisos:
                        try:
                            banco.salvar_entrada(sistema, cat.slug, {k: v for k, v in valores.items() if v is not None},
                                                 paginas=(p, p))
                        except (ValidationError, ValueError, KeyError):
                            pass  # fica só na saída; o Validador (próximo passo) cuida disso
            if ao_progresso:
                ao_progresso(feitas, len(paginas), len(brutas))
    return juntar_mesmo_nome(brutas)
