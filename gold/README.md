# Gold set

Gabarito feito à mão do que o sistema **deveria** extrair de recortes pequenos
dos livros. É a régua de todos os experimentos: baseline × multiagente,
Gemini × Claude, com e sem busca de contexto.

> **Status: rascunho.** Anotado a partir do texto extraído das páginas.
> Precisa ser conferido por uma pessoa com o livro aberto antes de valer como
> gabarito (veja a lista de conferência no fim).

## Arquivos

| arquivo | o que tem |
|---|---|
| `recortes.json` | quais páginas de cada livro entram na avaliação |
| `ordem-paranormal.jsonl` | 53 entradas + 3 opcionais + 2 negativos |
| `dnd-5e.jsonl` | 57 entradas + 1 opcional + 2 negativos |
| `exemplos/saida-exemplo-ordem.jsonl` | saída fictícia com erros de propósito, para ver o modo de comparação |

Os PDFs não estão no repositório. O nome do arquivo esperado em `livros/` está em `recortes.json`.
Páginas são **do PDF, contando a partir de 1** (não o número impresso, que tem deslocamento variável).

## Regra principal: o recorte é completo

Tudo o que há de conteúdo mecânico nas páginas do recorte está anotado. É isso que
permite medir **precisão** (o que o sistema extraiu e não está no gabarito é erro),
e não só cobertura.

## Tipos de linha

- **`entrada`** — deve ser extraída. Campos:
  - `nome`, `categoria_canonica`, `categoria_no_livro`, `paginas`
  - `atributos` — com chaves canônicas quando existem (`nivel`, `escola_elemento`,
    `execucao`, `alcance`, `alvo_area`, `duracao`, `resistencia`, `dados`,
    `aprimoramento`, `preco`, `peso`…) e chaves do sistema quando não
    (`discente`, `verdadeiro`, `critico`, `espacos`, `propriedades`…)
  - `descricao_contem` — trechos curtos que a descrição extraída deve conter
  - `dificuldade` — `normal`, `tabela`, `variantes`, `atravessa_pagina`
  - `fora_do_recorte` — atributos que só existem em páginas fora do recorte:
    só um sistema que **busca contexto** consegue preenchê-los
- **`opcional`** — extrair ou não, tanto faz (não conta para nenhum lado).
- **`negativo`** — página inteira que **não** deve gerar nenhuma entrada.

## Casos difíceis de propósito

| caso | onde | o que testa |
|---|---|---|
| entrada que começa antes do recorte | Banquete de Heróis, Envenenado (Ordem) | detectar "contexto insuficiente" e buscar a página anterior |
| entrada que termina depois do recorte | Compreensão Paranormal | buscar a página seguinte |
| sub-opções que parecem entradas | Chamas do Caos (Chamejar, Esquentar…) | não criar 4 rituais falsos |
| nomes quase iguais | Bola de Fogo × Bola de Fogo Controlável | não mesclar |
| repetição na tabela | Flechas, Balas curtas, Balas longas (Ordem) | deduplicar |
| cabeçalho em outra página | "Armas Táticas" está na p.64 | classe da arma depende de contexto |
| "ritual" com outro sentido | Boca Encantada (D&D) | no D&D é propriedade, não categoria |
| dano sem dado | Zarabatana (dano 1), Rede (sem dano) | validação de dados não pode rejeitar |
| lore com cara de entrada | Ordem p.304 (VERITUS, SENHOR VERÍSSIMO) | precisão / conteúdo indevido |

## Como conferir (Kevin e Aryel)

Use o revisor: `uv run compendio revisar`. Ele mostra a página ao lado das entradas e marca
com **!** os valores que não aparecem literalmente no texto — comece por eles.
Marque "conferido" em cada entrada revisada (o campo vai para o `.jsonl`).

Para cada recorte, com a página aberta:
1. Falta alguma entrada? Sobrou alguma que não existe?
2. Os valores dos atributos batem com o livro (sem corrigir erros do livro, ex.: "Beste Leve")?
3. Os `descricao_contem` aparecem de fato no texto?
4. Marque no fim desta página: `Conferido por: <nome>, <data>`.

Conferido por: —
