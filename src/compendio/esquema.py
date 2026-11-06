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
- Escreva em português com acentos normais (sem entidades HTML).{extra}"""

EXTRA_REVISAO = """
- `nomes_na_pagina`: o nome de TODA entrada dos tipos acima que aparece na página, inclusive as que
  estão em quadros laterais ou tabelas — mesmo as que você não extraiu.
- `precisa_de_contexto`: peça a página vizinha quando faltar algo que está nela:
  * a página começa no meio de uma entrada (há texto de regra antes do primeiro nome) →
    direcao "anterior", nome "" (o nome está na página anterior);
  * uma entrada continua na página seguinte → direcao "seguinte", com o nome dela;
  * campos de origem `cabecalho` sem nenhum cabeçalho visível acima das primeiras linhas →
    direcao "anterior", nome "", motivo "cabecalho".
  Não peça contexto se nada estiver faltando."""


class PedidoDeContexto(BaseModel):
    nome: str = Field(default="", description="nome da entrada, ou vazio se o nome está na outra página")
    direcao: Literal["anterior", "seguinte"]
    motivo: str = ""


def _descrever(cat: Categoria) -> str:
    linhas = [f"\n## {cat.nome} → lista `{cat.slug}`", f"Como identificar: {cat.descricao}"]
    for a in cat.atributos:
        linhas.append(f"- {a.nome} ({a.tipo}): {a.rotulo}. {a.descricao}")
    return "\n".join(linhas)


def _modelo_pagina(categorias: list[Categoria], revisao: bool = False) -> type[BaseModel]:
    campos: dict[str, Any] = {cat.slug: (list[modelo_entrada(cat)], Field(default_factory=list))
                              for cat in categorias}
    campos["incompletas"] = (list[str], Field(default_factory=list))
    if revisao:
        campos["nomes_na_pagina"] = (list[str], Field(default_factory=list))
        campos["precisa_de_contexto"] = (list[PedidoDeContexto], Field(default_factory=list))
    return create_model("PaginaRevisada" if revisao else "Pagina", **campos)


def _valores(cat: Categoria, bruto: dict) -> tuple[dict, list[str]]:
    """Valida a entrada contra o esquema; o que não validar fica como veio e vira aviso."""
    try:
        validado = modelo_entrada(cat).model_validate(bruto).model_dump()
        return validado, []
    except ValidationError as erro:
        return dict(bruto), [f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in erro.errors()]


def para_saida(cat: Categoria, valores: dict, pagina: int | tuple[int, int],
               avisos: list[str] | None = None) -> dict:
    """Chaves canônicas quando existem (é o que o VTT consulta); senão o nome do campo no sistema."""
    atributos: dict[str, Any] = {}
    for a in cat.atributos:
        v = valores.get(a.nome)
        if v in (None, "", []):
            continue
        chave = a.canonico if a.canonico and a.canonico not in atributos else a.nome
        atributos[chave] = limpar(v) if isinstance(v, str) else v
    paginas = list(pagina) if isinstance(pagina, tuple) else [pagina, pagina]
    d = {"sistema": cat.sistema, "categoria_canonica": cat.canonica, "categoria_no_livro": cat.nome,
         "nome": limpar(str(valores.get("nome", ""))), "paginas": paginas, "atributos": atributos,
         "descricao": limpar(str(valores.get("descricao") or ""))}
    if avisos:
        d["avisos"] = avisos
    return d


def extrair_pagina(llm: LLM, texto: str, pagina: int, categorias: list[Categoria], *, sistema: str,
                   modelo: str | None = None, revisao: bool = False, foco: str | None = None,
                   etapa: str = "especialista") -> tuple[list[tuple[Categoria, dict]], dict]:
    """Devolve [(categoria, valores brutos)] e o resto da resposta (incompletas, nomes, pedidos de contexto)."""
    extra = EXTRA_REVISAO if revisao else ""
    if foco:
        extra += f"\n\nFOCO DESTA CHAMADA: {foco}"
    instrucoes = INSTRUCOES_ESPECIALISTA.format(sistema=sistema, tipos="".join(_descrever(c) for c in categorias),
                                                extra=extra)
    respostas = estruturado_com_divisao(llm, etapa=etapa, instrucoes=instrucoes, prefixo=f"[Página {pagina}]",
                                        texto=texto, schema=_modelo_pagina(categorias, revisao), modelo=modelo)
    achadas: list[tuple[Categoria, dict]] = []
    info: dict[str, list] = {"incompletas": [], "nomes_na_pagina": [], "precisa_de_contexto": []}
    for d in respostas:
        info["incompletas"] += [limpar(n) for n in d.get("incompletas") or []]
        info["nomes_na_pagina"] += [limpar(n) for n in d.get("nomes_na_pagina") or [] if str(n).strip()]
        info["precisa_de_contexto"] += [x for x in d.get("precisa_de_contexto") or [] if isinstance(x, dict)]
        for cat in categorias:
            for bruto in d.get(cat.slug) or []:
                if isinstance(bruto, dict) and str(bruto.get("nome") or "").strip():
                    achadas.append((cat, bruto))
    return achadas, info


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


def _guardar(brutas: list[dict], banco, sistema: str, cat: Categoria, bruto: dict,
             paginas: tuple[int, int]) -> None:
    valores, avisos = _valores(cat, bruto)
    brutas.append(para_saida(cat, valores, paginas, avisos))
    if banco is not None and not avisos:
        try:
            banco.salvar_entrada(sistema, cat.slug, {k: v for k, v in valores.items() if v is not None},
                                 paginas=paginas)
        except (ValidationError, ValueError, KeyError):
            pass  # fica só na saída, com o aviso


def _mapear(llm, bloco, paginas, *, sistema, modelo_mapeador, banco, avisar) -> list[Categoria]:
    amostra = "\n\n".join(f"[Página {p}]\n{paginas[p]}" for p in bloco if paginas[p].strip())
    faixa = f"p.{bloco[0]}" + (f"–{bloco[-1]}" if len(bloco) > 1 else "")
    avisar(f"mapeando {faixa}…")
    categorias = descobrir(llm, amostra, sistema=sistema, modelo=modelo_mapeador) if amostra else []
    avisar(f"{faixa}: " + (", ".join(f"{c.nome} ({len(c.atributos)} campos)" for c in categorias)
                           or "sem conteúdo mecânico — não extrai"))
    if banco is not None:
        categorias = [banco.registrar_categoria(c)[0] for c in categorias]
    return categorias


def extrair(llm: LLM, paginas: dict[int, str], *, sistema: str, modelo: str | None = None,
            modelo_mapeador: str | None = None, banco=None,
            ao_progresso: Callable[[int, int, int], None] | None = None,
            ao_evento: Callable[[str], None] | None = None) -> list[dict]:
    """Mapeador + Especialista, sem revisão."""
    brutas: list[dict] = []
    feitas = 0
    avisar = ao_evento or (lambda _m: None)
    for bloco in _blocos(paginas):
        categorias = _mapear(llm, bloco, paginas, sistema=sistema, modelo_mapeador=modelo_mapeador,
                             banco=banco, avisar=avisar)
        for p in bloco:
            feitas += 1
            if categorias and paginas[p].strip():
                achadas, _ = extrair_pagina(llm, paginas[p], p, categorias, sistema=sistema, modelo=modelo)
                for cat, bruto in achadas:
                    _guardar(brutas, banco, sistema, cat, bruto, (p, p))
            if ao_progresso:
                ao_progresso(feitas, len(paginas), len(brutas))
    return juntar_mesmo_nome(brutas)


# ------------------------------------------------------- estratégia "agentes"

TRECHO_VIZINHO = 5_000  # caracteres da página vizinha mandados junto (fim da anterior / começo da seguinte)
TRECHO_CABECALHO = 2_500  # fim da página anterior dado como contexto quando o esquema tem campos de cabeçalho
MAX_PEDIDOS_POR_PAGINA = 3


def _posicao(nome: str, texto_norm: str) -> int:
    from .avaliacao import norm

    return texto_norm.rfind(norm(nome)) if norm(nome) else -1


def _filtrar_contexto(novas: list[tuple[Categoria, dict]], *, direcao: str, nome: str, texto: str,
                      vizinho: str) -> list[tuple[Categoria, dict]]:
    """O modelo costuma extrair a página vizinha inteira; aqui fica só o que foi pedido.

    - nome dado: só essa entrada;
    - 'anterior' sem nome: só a entrada cujo título aparece por ÚLTIMO no fim da página anterior
      (é a que continua na atual);
    - demais casos: só entradas cujo nome aparece na página atual.
    """
    from .avaliacao import norm

    if nome:
        alvo = norm(nome)
        return [(c, b) for c, b in novas if norm(b.get("nome", "")) == alvo or alvo in norm(b.get("nome", ""))]
    if direcao == "anterior":
        viz = norm(vizinho[-TRECHO_VIZINHO:])
        com_pos = [(c, b, _posicao(b.get("nome", ""), viz)) for c, b in novas]
        com_pos = [x for x in com_pos if x[2] >= 0]
        return [max(com_pos, key=lambda x: x[2])[:2]] if com_pos else []
    pagina = norm(texto)
    return [(c, b) for c, b in novas if _posicao(b.get("nome", ""), pagina) >= 0]


def _tem_cabecalho(categorias: list[Categoria]) -> bool:
    return any(a.descricao.startswith("[cabecalho]") for c in categorias for a in c.atributos)


def extrair_com_revisao(llm: LLM, paginas: dict[int, str], *, sistema: str, modelo: str | None = None,
                        modelo_mapeador: str | None = None, banco=None,
                        buscar_pagina: Callable[[int], str] | None = None,
                        ao_progresso: Callable[[int, int, int], None] | None = None,
                        ao_evento: Callable[[str], None] | None = None) -> list[dict]:
    """Mapeador + Especialista + Revisor de cobertura + busca de contexto na página vizinha.

    O Especialista agora também diz (1) todos os nomes que viu na página e (2) quando precisa de outra
    página. Quem decide buscar é ele; o laço abaixo só executa o pedido (a tool `buscar_pagina`),
    com limite de pedidos por página, e chama o Especialista de novo com foco no que faltou.
    """
    from .avaliacao import norm

    buscar = buscar_pagina or (lambda q: paginas.get(q, ""))
    avisar = ao_evento or (lambda _m: None)
    do_contexto: list[dict] = []  # entram primeiro na junção: o que veio com contexto completa o resto
    brutas: list[dict] = []
    feitas = 0
    for bloco in _blocos(paginas):
        categorias = _mapear(llm, bloco, paginas, sistema=sistema, modelo_mapeador=modelo_mapeador,
                             banco=banco, avisar=avisar)
        for p in bloco:
            feitas += 1
            texto = paginas[p]
            if not (categorias and texto.strip()):
                if ao_progresso:
                    ao_progresso(feitas, len(paginas), len(brutas) + len(do_contexto))
                continue
            entrada_texto = texto
            if p == bloco[0] and _tem_cabecalho(categorias) and p > 1:
                anterior = buscar(p - 1)
                if anterior.strip():  # o cabeçalho do grupo pode ter ficado na página anterior
                    entrada_texto = (f"[fim da Página {p - 1} — só contexto de cabeçalhos, não extraia entradas daqui]\n"
                                     f"{anterior[-TRECHO_CABECALHO:]}\n\n[Página {p}]\n{texto}")
                    avisar(f"p.{p}: esquema tem campos de cabeçalho — inclui o fim da p.{p - 1} como contexto")
            achadas, info = extrair_pagina(llm, entrada_texto, p, categorias, sistema=sistema, modelo=modelo,
                                           revisao=True)
            if entrada_texto is not texto:
                achadas = _filtrar_contexto(achadas, direcao="cabecalho", nome="", texto=texto, vizinho="")
            for cat, bruto in achadas:
                _guardar(brutas, banco, sistema, cat, bruto, (p, p))

            # Revisor de cobertura: nomes que o próprio Especialista viu e não extraiu
            extraidos = {norm(b.get("nome", "")) for _, b in achadas}
            faltando = list(dict.fromkeys(n for n in info["nomes_na_pagina"] if norm(n) not in extraidos))
            if faltando:
                avisar(f"p.{p}: revisor pede de novo {', '.join(faltando[:6])}" + ("…" if len(faltando) > 6 else ""))
                novas, _ = extrair_pagina(llm, texto, p, categorias, sistema=sistema, modelo=modelo, etapa="revisor",
                                          foco="extraia SOMENTE estas entradas, completas: " + "; ".join(faltando))
                for cat, bruto in novas:
                    _guardar(brutas, banco, sistema, cat, bruto, (p, p))

            # Contexto: o Especialista pediu a página vizinha
            pedidos = list(info["precisa_de_contexto"])
            ja_pedidos = {norm(str(x.get("nome", ""))) for x in pedidos}
            for n in info["incompletas"]:  # o próprio Especialista disse que a entrada está incompleta
                if norm(n) not in ja_pedidos and _posicao(n, norm(texto)) >= 0:
                    pedidos.append({"nome": n, "direcao": "seguinte", "motivo": "marcada como incompleta"})
            pedidos = pedidos[:MAX_PEDIDOS_POR_PAGINA]
            vistos: set[tuple[str, str]] = set()
            for pedido in pedidos:
                direcao, nome = pedido.get("direcao"), limpar(str(pedido.get("nome") or ""))
                if direcao not in ("anterior", "seguinte") or (direcao, nome) in vistos:
                    continue
                vistos.add((direcao, nome))
                q = p - 1 if direcao == "anterior" else p + 1
                vizinho = buscar(q) if q >= 1 else ""
                if not vizinho.strip():
                    continue
                cabecalho = "cabecalho" in norm(str(pedido.get("motivo", "")))
                if direcao == "anterior":
                    combinado = f"[fim da Página {q}]\n{vizinho[-TRECHO_VIZINHO:]}\n\n[Página {p}]\n{texto}"
                    foco = ("extraia de novo TODAS as entradas da página " + str(p) + ", usando os cabeçalhos da página anterior"
                            if cabecalho else
                            f"extraia SOMENTE a entrada '{nome}'" if nome else
                            f"extraia SOMENTE a entrada que começa na página {q} e termina no início da página {p}")
                    faixa = (q, p)
                else:
                    combinado = f"[Página {p}]\n{texto}\n\n[começo da Página {q}]\n{vizinho[:TRECHO_VIZINHO]}"
                    foco = f"extraia SOMENTE a entrada '{nome}', completa, incluindo o que está na página {q}"
                    faixa = (p, q)
                avisar(f"p.{p}: busca contexto na p.{q} ({nome or pedido.get('motivo') or 'entrada sem nome'})")
                novas, _ = extrair_pagina(llm, combinado, p, categorias, sistema=sistema, modelo=modelo,
                                          etapa="contexto", foco=foco)
                bruto_n = len(novas)
                novas = _filtrar_contexto(novas, direcao="cabecalho" if cabecalho else direcao, nome=nome,
                                          texto=texto, vizinho=vizinho)
                avisar(f"p.{p}: contexto trouxe " + (", ".join(b.get("nome", "?") for _, b in novas) or "nada")
                       + (f" (descartou {bruto_n - len(novas)} de fora do pedido)" if bruto_n > len(novas) else ""))
                for cat, bruto in novas:
                    _guardar(do_contexto, banco, sistema, cat, bruto, faixa if not cabecalho else (p, p))
            if ao_progresso:
                ao_progresso(feitas, len(paginas), len(brutas) + len(do_contexto))
    return juntar_mesmo_nome(do_contexto + brutas)
