# Compêndio RPG

Sistema multiagente que lê livros de RPG (PDF) e monta um **compêndio consultável**
de regras, equipamentos, magias/rituais, opções de personagem e criaturas —
gastando o mínimo de tokens possível.

Projeto da disciplina de Sistemas Multiagente (IFPB) — Kevin Ryan e Aryel Sousa.
Pensado para virar uma ferramenta do VTT **RPG Master Suite**.

## Ideia central

1. **O índice do livro guia tudo.** O PDF é quebrado por seção do índice (via
   [pdfscope](../pdfscope)); o Mapeador lê só o índice (poucas centenas de
   tokens) para decidir o que vai para cada especialista.
2. **O esquema é descoberto, não escrito à mão.** Ao achar os rituais do Ordem
   Paranormal, o sistema registra a categoria *Ritual* com seus atributos
   (elemento, círculo, execução, alcance, alvo, duração, resistência, custo, dados…).
   O banco cria uma view com uma coluna por atributo, e atributos novos que
   aparecem depois são adicionados sozinhos.
3. **Camada canônica.** *Ritual* (Ordem) e *Magia* (D&D) apontam para
   `efeito_sobrenatural`; *Círculo* e *Nível* para `nivel`; *Execução* e
   *Tempo de Conjuração* para `execucao`. O VTT consulta entre sistemas, e os
   agentes reconhecem conteúdos equivalentes com nomes diferentes.

```
PDF ─► pdfscope (índice + texto + busca)
        │
        ▼
  [Mapeador]  índice → roteamento + glossário do sistema          (sprint 2)
        ├─► [Especialista efeito_sobrenatural] ┐  tool buscar_trecho()
        ├─► [Especialista equipamento]         ┤  pede contexto quando falta
        └─► [Especialista regra]               ┘
                                               ▼
                                        [Validador]  schema + dados + duplicatas
                                               ▼
                         SQLite: categorias/atributos dinâmicos + views
```

## Instalação (Windows, PyCharm ou terminal)

Pré-requisitos: Python 3.12 e [uv](https://docs.astral.sh/uv/). As pastas
`pdfscope` e `compendio-rpg` precisam estar lado a lado.

```powershell
cd C:\Users\kevin\PycharmProjects\compendio-rpg
uv sync
copy .env.example .env      # e cole a GEMINI_API_KEY
uv run compendio verificar --api
uv run pytest
```

## Comandos

| comando | o que faz |
|---|---|
| `uv run compendio verificar [--api] [--provedor claude]` | confere o `.env` e, com `--api`, faz uma chamada mínima a cada modelo |
| `uv run compendio indice livros\X.pdf` | mostra o índice compacto e quantos tokens ele custa |
| `uv run compendio ingerir livros\X.pdf` | gera `data/chunks/X.jsonl` e um diagnóstico do PDF |
| `uv run compendio demo` | cria `data/demo.db` com um ritual e uma magia de exemplo |
| `uv run compendio banco` | lista categorias, atributos e entradas do compêndio |

Os PDFs ficam em `livros/`, que está no `.gitignore` (direitos autorais).

## Estrutura

```
src/compendio/
  ingest.py          PDF -> chunks guiados pelo índice + diagnóstico
  llm.py             Gemini e Claude com a mesma interface: saída estruturada, retentativas, tokens por etapa
  dados.py           expressões de dados (3d6+2): extrair, normalizar, faixa min/max
  schema/canonico.py vocabulário comum entre sistemas (categorias, atributos, sinônimos)
  schema/registro.py Categoria/Atributo dinâmicos -> modelo Pydantic -> JSON Schema
  storage/banco.py   SQLite com tabelas fixas + uma view por categoria
  exemplo.py         categorias de exemplo (Ritual/Ordem, Magia/D&D) para demo e testes
  cli.py             linha de comando
```

## LLM

O provedor é escolhido no `.env` com `COMPENDIO_PROVEDOR`:

| provedor | quando usar | modelos padrão (rápido / forte) |
|---|---|---|
| `gemini` (padrão) | desenvolvimento e testes: tem uso gratuito no [AI Studio](https://aistudio.google.com/apikey), com limite de requisições | `gemini-3.5-flash-lite` / `gemini-3.8-flash` |
| `claude` | rodadas de comparação; a API é cobrada à parte do plano do Claude (Max/Team incluem créditos mensais) | `claude-haiku-5-5` / `claude-sonnet-5-5` |

- **rápido**: extração em volume (cada trecho); **forte**: mapear o livro, descobrir esquemas, validar.
- Os dois devolvem saída estruturada no mesmo formato, então o resto do sistema não muda.
- Em erro de limite de taxa (429, comum no plano grátis) a chamada é repetida com espera exponencial.
- Toda chamada é registrada por etapa (`RegistroDeUso`) com tokens de entrada, saída e cache —
  é daí que saem as métricas de custo, e é o que permite comparar os dois provedores no mesmo gold set.

Andamento das sprints: [docs/SPRINTS.md](docs/SPRINTS.md).
