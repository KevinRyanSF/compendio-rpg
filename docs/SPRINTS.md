# Andamento das sprints

Registro para o formulário do Classroom: o que foi decidido, por quê e com qual evidência.

## Pontos levantados na Sprint 0 (leitura do professor)

> "Workflow de extração paralela; agenticidade ainda precisa ser caracterizada."

- Um único extrator LLM com saída estruturada já resolve boa parte? → **é o nosso baseline**.
- Os agentes interagem ou só executam em paralelo? → Mapeador → especialistas → Validador, com devolução.
- Como medir precisão, cobertura e conteúdo indevido? → gold set + script de avaliação (passo 4).
- O sistema detecta "não tenho contexto suficiente"? → campos `contexto_insuficiente` / `buscar` no lote
  e a tool `buscar_trecho`.

Teste sugerido: gold set pequeno; comparar extração numa passada × versão que busca contexto e revisa.

## Sprint 1 — base e baseline

- [x] 1. Repositório, pdfscope separado, ingestão guiada pelo índice
- [x] (extra) Banco com categorias/atributos dinâmicos e camada canônica
- [x] 2. Gold set em `gold/` (Ordem: 53 entradas, D&D: 57, + opcionais e páginas negativas), conferido no revisor visual
- [x] (extra) Revisor visual do gabarito e das saídas (`compendio revisar`)
- [x] 3. Baseline: 1 LLM, uma chamada por página, saída estruturada (`compendio extrair`)
- [x] 4. Avaliação: precisão, cobertura, F1, indevidos, atributos, contexto recuperado e tokens → `resultados/resultados.csv`

## Sprint 2 — multiagente + RAG

- [ ] 5. Busca híbrida: literal (pdfscope) + semântica + glossário do sistema
- [x] 6. Mapeador: descoberta de categorias/atributos (`--estrategia esquema`)
      (roteamento pelo índice fica para quando rodar no livro inteiro)
- [x] 7. Agente de contexto com a tool `buscar_pagina` + Revisor de cobertura (`--estrategia agentes`)
- [~] 8. Validação: tipos do esquema (Pydantic) + regra de título + filtro do contexto; devolução ao especialista via Revisor
- [x] 9. Baseline × multiagente no gold set → tabela de resultados (abaixo)

## Achados ao ingerir os livros reais

| livro | páginas | índice (bookmarks) | tokens estimados | observações |
|---|---|---|---|---|
| Ordem Paranormal v1.2 | 330 | 238 entradas, 4 níveis | ~197 mil (era ~208 mil antes de tirar a marca d'água) | rituais não estão no índice: "Descrição dos Rituais" vira 7 chunks; ícones de dado saem como "O" (ex.: "–O") |
| D&D 5 edição | 314 | **nenhum** | ~339 mil | tem sumário impresso na p.2, mas o número impresso tem deslocamento variável (−1 a −3) em relação à página do PDF; páginas só de arte não têm texto |

Consequências:
- **Linhas repetidas** em quase todas as páginas (marca d'água com nome e e-mail do comprador, rodapés) agora são
  removidas na ingestão — economizam tokens e não levam dado pessoal para o LLM/banco.
- **Livro sem índice** é o primeiro trabalho de verdade para o Mapeador: reconstruir o índice a partir do sumário
  impresso (ou de títulos detectados por fonte com `pdfscope.page_lines`) e corrigir o deslocamento de páginas.
- Para o índice do Ordem inteiro, o Mapeador gasta ~1,8 mil tokens; o livro inteiro custaria ~197 mil.

## Primeira rodada do baseline (Gemini rápido, 06/11)

**Ordem Paranormal** — 6 chamadas, ~6,5 mil tokens de entrada, 18 s:
precisão 93%, cobertura 94%, atributos corretos 61% (+16% com o valor certo em outro nome de campo),
contexto recuperado 0/14.

O que deu errado e o que isso diz sobre a próxima versão:
- **Acentos quebrados pelo modelo leve** ("F&iacute;sico", "padr'ao"): 2 rituais contados como
  faltando *e* sobrando. → limpeza de entidades HTML + instrução no prompt.
- **Mesmo valor, nome de campo diferente** ("tipo" em vez de "tipo_dano"; "CONHECIMENTO 1" num campo
  só, em vez de elemento + círculo). → sem um esquema por sistema, cada página inventa seus nomes.
  É o argumento para o **Mapeador descobrir o esquema da categoria** antes de extrair.
- **Formas Discente/Verdadeiro perdidas** e cabeçalhos de grupo da tabela ("Corpo a Corpo – Duas
  Mãos") ignorados. → o esquema descoberto precisa listar esses campos.
- **Contexto 0/14**: nada do que está em outra página foi recuperado (esperado para o baseline).
  → é o que o especialista com `buscar_trecho` precisa melhorar.

**D&D** — a página 150 (37 armas) estourou o limite de 4.096 tokens de saída e o JSON veio cortado.
→ limite de 16 mil tokens e, se ainda cortar, a página é dividida ao meio automaticamente.

## Segunda rodada do baseline (com as correções, 06/11)

| livro | precisão | cobertura | F1 | atributos corretos | valor com outro nome | contexto | chamadas | tokens entrada/saída | tempo |
|---|---|---|---|---|---|---|---|---|---|
| Ordem Paranormal | 100% | 98% | 99% | 68% | +15% | 0/14 | 6 | 6,7 mil / 7,1 mil | 18 s |
| D&D 5e | 100% | 98% | 99% | 57% | +14% | 0/1 | 7 | 9,9 mil / 7,6 mil | 25 s |

**Conclusão: o baseline já resolve a detecção; o problema é a estrutura e o contexto.**
Nenhum valor extraído estava errado — todos os erros de atributo são de *estrutura*:

1. **Campo herdado do cabeçalho da tabela** não vem na linha: classe/empunhadura das armas
   (Simples/Marcial, "Corpo a Corpo – Duas Mãos") — 18 no Ordem, 74 no D&D.
2. **Campos fundidos**: "1d4 perfurante" (dano + tipo), "3° nível de evocação" (nível + escola),
   "SANGUE 2" (elemento + círculo).
3. **Campos escondidos na prosa**: Discente/Verdadeiro, "Em Níveis Superiores", resistência, dados, ritual.
4. **Contexto**: as duas únicas entradas que faltaram (Envenenado, Banquete de Heróis) começam na
   página anterior ao recorte.

Isso define a Sprint 2 pela evidência, não pela arquitetura desejada:
- **Mapeador / descoberta de esquema** → resolve 1, 2 e 3 (cada categoria ganha a lista de campos,
  incluindo os herdados do cabeçalho e os que ficam na prosa).
- **Validador determinístico** → separa campos fundidos (dados com `dados.py`, nível/escola).
- **Especialista com `buscar_trecho`** → resolve 4.
- Critério de sucesso: subir "atributos corretos" e "contexto" **sem perder** precisão/cobertura,
  com custo de tokens medido (o baseline custa ~14 mil tokens por livro nos recortes).

## Estratégia "esquema" (Mapeador + Especialista, Gemini rápido nos dois, 06/11)

| livro | estratégia | precisão | cobertura | atributos corretos | outro nome | contexto | chamadas | tokens entrada/saída | tempo |
|---|---|---|---|---|---|---|---|---|---|
| Ordem | baseline | 100% | 98% | 68% | +15% | 0/14 | 6 | 6,7 mil / 7,1 mil | 18 s |
| Ordem | **esquema** | 100% | 94% | **86%** | +5% | 0/14 | 9 | 14,5 mil / 7,0 mil | 23 s |
| D&D | baseline | 100% | 98% | 57% | +14% | 0/1 | 7 | 9,9 mil / 7,6 mil | 25 s |
| D&D | **esquema** | 100% | 96% | **95%** | +2% | 0/1 | 9 | 18,6 mil / 9,2 mil | 31 s |

- O esquema descoberto resolve o problema de estrutura: +18 pontos no Ordem, +38 no D&D.
  Ex.: Arma ganhou `grupo` e `empunhadura` vindos do **cabeçalho** da tabela e `dano` separado de
  `tipo_dano`; Ritual ganhou `elemento` + `circulo` a partir da **linha sem rótulo** "SANGUE 2".
- Custo: ~2× tokens de entrada (o Mapeador lê o recorte inteiro uma vez), mesma saída, tempo parecido.
  Páginas sem conteúdo mecânico (prefácio, lore) não chegam ao Especialista.
- Perdeu um pouco de cobertura: o Especialista **pulou** entradas (Chamas do Caos, Cicatrização,
  Exaustão no quadro lateral) → motiva o **Revisor de cobertura**.
- Contexto continua 0 → motiva o **agente de contexto**.
- Problemas que ficaram: Zarabatana (dano fixo "1") era recusada pela validação de dados — corrigido;
  o Mapeador juntou Discente/Verdadeiro em `aprimoramento` (informação certa, granularidade diferente).
- O modelo forte como Mapeador estourou o prazo (504) no plano grátis; o rápido fez o trabalho bem.

## Estratégia "agentes" (+ Revisor de cobertura + agente de contexto)

- O Especialista passa a devolver também `nomes_na_pagina` (tudo o que viu) e `precisa_de_contexto`
  (pedidos de página anterior/seguinte, com o motivo).
- **Revisor de cobertura**: nomes vistos e não extraídos → nova chamada focada só neles.
- **Agente de contexto**: para cada pedido (máx. 3 por página) o laço executa a tool `buscar_pagina`
  (qualquer página do livro, já limpa) e chama o Especialista de novo com o trecho vizinho e um foco.
  Quem decide buscar é o modelo; o código só executa e limita — é o "salto agentivo" da Sprint 0.

**Primeira rodada (06/11):**

| livro | precisão | cobertura | F1 | atributos | contexto | chamadas | tokens entrada/saída | tempo |
|---|---|---|---|---|---|---|---|---|
| Ordem | 79% | **100%** | 88% | 84% | 1/14 | 12 | 19,9 mil / 8,3 mil | 28 s |
| D&D | **100%** | **100%** | **100%** | 95% | 0/1 | 14 | 30,5 mil / 12,1 mil | 48 s |

- O **Revisor de cobertura** funcionou: recuperou as entradas puladas (Exaustão no quadro lateral,
  as condições do Ordem, Banquete de Heróis) → cobertura 100% nos dois livros.
- O **agente de contexto** pediu a página certa (p.318 para Envenenado, p.220 para Banquete), mas o
  modelo extraiu a página vizinha **inteira**: 14 condições da p.318 entraram como sobra (precisão 79%).
  → o controle agora **filtra** a resposta: com nome pedido, só ela; "anterior" sem nome, só a entrada
  cujo título aparece por último na página anterior; nos demais casos, só o que aparece na página atual.
- O modelo só pediu contexto quando a página começa no meio de uma entrada; não pediu para o cabeçalho
  "Armas Táticas" (p.64) nem para Compreensão Paranormal, que ele mesmo marcou como incompleta.
  → gatilhos determinísticos: `incompletas` viram pedido da página seguinte; categoria com campos de
  cabeçalho recebe o fim da página anterior como contexto na primeira página do recorte.
**Segunda rodada (com filtro e gatilhos, 06/11):**

| livro | precisão | cobertura | F1 | atributos | contexto | chamadas | tokens entrada/saída | tempo |
|---|---|---|---|---|---|---|---|---|
| Ordem | 100% | 98% | 99% | 81% | 1/14 | 10 | 18,6 mil / 7,9 mil | 24 s |
| D&D | 98% | **100%** | 99% | 96% | **1/1** | 15 | 33,9 mil / 13,5 mil | 40 s |

- O filtro resolveu as sobras do Ordem; Banquete de Heróis veio **completo** da p.220 e Compreensão
  Paranormal buscou a p.135 sozinha (marcada como incompleta).
- Novo erro: o Especialista listou "CONTA BRILHANTE" (objeto citado na descrição de Bola de Fogo
  Controlável) como entrada; o Revisor e o contexto acreditaram, e o 12d6 da magia foi parar nela.
  O filtro também casou "BOLA DE FOGO" dentro de "BOLA DE FOGO CONTROLÁVEL".
  → **regra de título**: um nome só vale como entrada se aparece no começo de uma linha
  ("Esmorecido. …", "Acha I 1d12", "BOLA DE FOGO"); vale para o Revisor, para pedidos de contexto e
  para o filtro. Conferido: os 110 nomes do gold set passam na regra.
- Envenenado voltou a faltar: desta vez o modelo não pediu contexto.
  → **detector de continuação**: a primeira linha de conteúdo começa com minúscula/pontuação ou com um
  rótulo do esquema ("Componentes: …"). Nos recortes, dispara exatamente nas p.319 e p.221.
- "Armas Táticas": com o fim da p.64 o modelo ainda pôs o subcabeçalho no campo de grupo
  → instrução explícita sobre cabeçalhos em dois níveis.

**Terceira rodada (06/11, 15h50):** Ordem — precisão 100%, cobertura 98%, atributos 88%,
**contexto 12/14** ("Armas Táticas" vindo da p.64), 9 chamadas, 16 mil tokens de entrada.
D&D — precisão 100%, cobertura 98%, atributos 96%, contexto 0/1.

⚠️ **Erro de base encontrado aqui**: o filtro achou "BÊNÇÃO" como última magia da p.221 e o detector de
continuação não disparou na p.319. Causa: `pdfscope.page_text_raw` usava `sort=True`, que ordena os blocos
por altura e **intercala as duas colunas** das páginas. No ambiente de desenvolvimento os testes usavam
outro leitor (pypdfium2), que mantém a ordem das colunas, por isso não apareceu antes.
→ pdfscope 0.4.0 lê na ordem do PDF por padrão. **Todas as rodadas anteriores (inclusive o baseline)
usaram texto com colunas misturadas** e precisam ser refeitas para a tabela final.
Também: título quebrado em duas linhas passa a ser reconhecido, e pedido "anterior" com nome que não é
título vira pedido sem nome (em vez de ser ignorado).

- Correções na régua (valem para todas as estratégias; baseline e esquema não mudaram):
  categoria "I" guardada como inteiro 1 agora conta como certa; opcionais aceitam variações de nome
  ("Armas Improvisadas").

## Resultado final das Sprints 1–2 (texto na ordem certa, pdfscope 0.4.0, 06/11 ~16h)

Todas com Gemini rápido (`gemini-3.5-flash-lite`, reserva `3.1-flash-lite`), mesmos recortes e mesma régua.

| livro | estratégia | precisão | cobertura | F1 | atributos corretos | contexto | chamadas | tokens entrada / saída |
|---|---|---|---|---|---|---|---|---|
| Ordem | baseline | 100% | 98% | 99% | 61% | 0/14 | 6 | 6,6 mil / 7,5 mil |
| Ordem | esquema | 100% | 96% | 98% | 81% | 0/14 | 9 | 14,7 mil / 7,8 mil |
| Ordem | **agentes** | 98%¹ | **100%** | 99% | **91%** | **14/14** | 12 | 22,8 mil / 13,3 mil |
| D&D | baseline | 100% | 98% | 99% | 55% | 0/1 | 7 | 10,4 mil / 8,5 mil |
| D&D | esquema | 100% | 98% | 99% | 94% | 0/1 | 9 | 19,7 mil / 9,3 mil |
| D&D | **agentes** | **100%** | **100%** | **100%** | **97%** | **1/1** | 12 | 27,2 mil / 12,2 mil |

¹ a única sobra foi "Lança" (p.64) aceita porque "Lança-chamas" começa com "Lança"; regra de título corrigida depois.

**Leitura:**
- Detectar entradas o baseline já fazia (F1 99%). O ganho do sistema multiagente está onde o baseline falhava:
  **estrutura** (atributos: 61→91% no Ordem, 55→97% no D&D) e **contexto** (0→14/14 e 0→1/1).
- Cada papel tem um efeito mensurável: o **Mapeador** (esquema) dá o salto de atributos; o **Revisor** e o
  **agente de contexto** fecham cobertura e contexto.
- Custo: ~3× tokens de entrada e ~1,6× de saída em relação ao baseline (≈36 mil tokens por livro nos recortes),
  tempo parecido (~37 s). Páginas sem conteúdo mecânico não gastam extração.
- O que **não** funcionou bem e foi corrigido no caminho: aceitar a resposta do modelo sem filtro (página vizinha
  inteira), confiar que o modelo pede contexto (precisou de gatilhos determinísticos), aceitar qualquer nome
  como entrada (regra de título) e — erro de base — ler o PDF com as colunas intercaladas.

**Limitações que permanecem:**
- Gold set pequeno (2 livros, 110 entradas, 11 páginas) e **uma execução por configuração** — falta medir variância
  (o modelo não é determinístico; ex.: cobertura do esquema variou 94–96% entre rodadas no Ordem).
- Avaliado só nos recortes: o sistema ainda não roda no livro inteiro (o Mapeador não roteia pelo índice e o D&D
  não tem índice — precisa reconstruir pelo sumário impresso).
- Sem busca semântica/glossário (magia ≈ ritual) — a camada canônica existe, mas a recuperação ainda é por página.
- Granularidade do esquema varia entre rodadas (ex.: Discente/Verdadeiro juntos em `aprimoramento`).
- Só Gemini no plano grátis; o modelo forte deu 504 e ficou fora; Claude não foi comparado.

## Decisões

| decisão | motivo |
|---|---|
| Chunking pelo índice do PDF | o índice é barato (poucos tokens) e já diz onde está cada coisa |
| Esquema dinâmico (categoria + atributos no banco, view por categoria) | serve para qualquer sistema sem código novo; o VTT consulta como tabela |
| Camada canônica (`efeito_sobrenatural`, `nivel`, `execucao`…) | magia/ritual, círculo/nível etc. são nomes diferentes para a mesma mecânica |
| Dados (3d6+2) validados fora do LLM | determinístico, verificável e é o que o VTT precisa para rolar |
| Saída estruturada (JSON Schema) nos dois provedores | formato garantido e validado pelo Pydantic |
| Mapeador no modelo rápido | o forte estourou o prazo (504) no plano grátis; o rápido descobriu bons esquemas |
| Filtro determinístico na resposta do contexto | o modelo extrai a página vizinha inteira se deixar |
| Gatilhos determinísticos de contexto (continuação, incompletas, cabeçalho) | o modelo nem sempre pede contexto quando precisa |
| Regra de título (nome no começo da linha) | evita entradas falsas citadas na prosa ("conta brilhante") |
| Ler o PDF na ordem do arquivo (sem `sort`) | `sort=True` intercala colunas e embaralha o texto |
| Gemini como padrão, Claude como opção | Gemini tem uso gratuito e é o da disciplina; trocar de provedor permite comparar custo/qualidade no gold set |
