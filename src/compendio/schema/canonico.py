"""A camada canônica: o vocabulário comum entre sistemas.

Cada sistema tem seus nomes ("Magia" no D&D, "Ritual" no Ordem Paranormal), mas
eles apontam para a mesma categoria canônica (`efeito_sobrenatural`). O mesmo vale
para atributos: "Tempo de Conjuração" (D&D) e "Execução" (Ordem) -> `execucao`.

É isso que permite ao VTT perguntar "todos os efeitos sobrenaturais com alcance
curto" sem saber de qual sistema vieram, e que permite ao agente de magias do
D&D reconhecer os rituais do Ordem.

Estes dicionários são a semente. O Mapeador amplia o glossário de cada sistema
(tabela `termos` no banco) quando lê um livro novo.
"""

from __future__ import annotations

import re
import unicodedata

CATEGORIAS: dict[str, str] = {
    "efeito_sobrenatural": "Magias, rituais, milagres, poderes psíquicos, truques — efeitos que um personagem conjura ou ativa.",
    "equipamento": "Armas, armaduras, itens, consumíveis, veículos, ferramentas.",
    "regra": "Regras de jogo: testes, condições, ações de combate, descanso, mecânicas gerais.",
    "opcao_personagem": "Classes, origens, raças/ancestralidades, trilhas, talentos, poderes de classe, perícias.",
    "criatura": "Monstros, ameaças, NPCs e criaturas com estatísticas.",
    "outro": "Conteúdo mecânico que não cabe nas demais.",
}

ATRIBUTOS: dict[str, str] = {
    "nivel": "Nível, círculo, grau ou patamar de poder",
    "escola_elemento": "Escola, elemento, tradição, tipo ou afinidade",
    "execucao": "Tempo ou tipo de ação para usar (tempo de conjuração, execução)",
    "alcance": "Distância máxima do efeito",
    "alvo_area": "Alvo, área ou efeito",
    "duracao": "Quanto tempo o efeito dura",
    "resistencia": "Teste para resistir ou evitar (salvaguarda, resistência)",
    "custo": "Recurso gasto: PE, PM, espaço de magia, sanidade, componentes materiais",
    "componentes": "Componentes exigidos (verbal, somático, material)",
    "dados": "Dados rolados no efeito (dano, cura, duração variável)",
    "dano": "Dano causado (normalmente uma expressão de dados) e tipo",
    "protecao": "Defesa, CA ou redução de dano concedida",
    "preco": "Preço ou categoria de custo do item",
    "peso": "Peso, carga ou espaços ocupados",
    "pre_requisito": "Pré-requisitos para obter",
    "aprimoramento": "Versões aprimoradas / em níveis superiores / discente e verdadeiro",
}

# termo (normalizado) -> categoria canônica
SINONIMOS_CATEGORIA: dict[str, str] = {
    "magia": "efeito_sobrenatural",
    "magias": "efeito_sobrenatural",
    "ritual": "efeito_sobrenatural",
    "rituais": "efeito_sobrenatural",
    "feitico": "efeito_sobrenatural",
    "milagre": "efeito_sobrenatural",
    "truque": "efeito_sobrenatural",
    "poder psiquico": "efeito_sobrenatural",
    "spell": "efeito_sobrenatural",
    "arma": "equipamento",
    "armas": "equipamento",
    "armadura": "equipamento",
    "item": "equipamento",
    "itens": "equipamento",
    "equipamento": "equipamento",
    "classe": "opcao_personagem",
    "origem": "opcao_personagem",
    "trilha": "opcao_personagem",
    "talento": "opcao_personagem",
    "raca": "opcao_personagem",
    "monstro": "criatura",
    "ameaca": "criatura",
    "criatura": "criatura",
    "condicao": "regra",
    "regra": "regra",
}

# termo (normalizado) -> atributo canônico
SINONIMOS_ATRIBUTO: dict[str, str] = {
    "circulo": "nivel",
    "nivel": "nivel",
    "escola": "escola_elemento",
    "elemento": "escola_elemento",
    "execucao": "execucao",
    "tempo de conjuracao": "execucao",
    "alcance": "alcance",
    "alvo": "alvo_area",
    "area": "alvo_area",
    "efeito": "alvo_area",
    "duracao": "duracao",
    "resistencia": "resistencia",
    "salvaguarda": "resistencia",
    "custo": "custo",
    "custo em pe": "custo",
    "componentes": "componentes",
    "dano": "dano",
    "dados": "dados",
    "defesa": "protecao",
    "ca": "protecao",
    "preco": "preco",
    "peso": "peso",
    "espacos": "peso",
    "pre-requisito": "pre_requisito",
    "pre-requisitos": "pre_requisito",
    "em niveis superiores": "aprimoramento",
}


def normalizar(texto: str) -> str:
    """minúsculas, sem acento, espaços simples."""
    sem_acento = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", sem_acento).strip().lower()


def slug(texto: str) -> str:
    """Identificador seguro para SQL e Python: 'Tempo de Conjuração' -> 'tempo_de_conjuracao'."""
    s = re.sub(r"[^a-z0-9]+", "_", normalizar(texto)).strip("_")
    if not s:
        raise ValueError(f"não dá para gerar identificador a partir de {texto!r}")
    return f"_{s}" if s[0].isdigit() else s


def categoria_por_termo(termo: str) -> str | None:
    return SINONIMOS_CATEGORIA.get(normalizar(termo))


def atributo_por_termo(termo: str) -> str | None:
    return SINONIMOS_ATRIBUTO.get(normalizar(termo))
