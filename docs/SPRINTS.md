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
- [~] 3. Baseline: 1 LLM, uma chamada por página, saída estruturada (`compendio extrair`) — falta rodar
- [x] 4. Avaliação: precisão, cobertura, F1, indevidos, atributos, contexto recuperado e tokens → `resultados/resultados.csv`

## Sprint 2 — multiagente + RAG

- [ ] 5. Busca híbrida: literal (pdfscope) + semântica + glossário do sistema
- [ ] 6. Mapeador: roteamento pelo índice + descoberta de categorias/atributos
- [ ] 7. Especialistas com `buscar_trecho` (o salto agentivo)
- [ ] 8. Validador com devolução ao especialista
- [ ] 9. Baseline × multiagente no gold set → tabela de resultados

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

## Decisões

| decisão | motivo |
|---|---|
| Chunking pelo índice do PDF | o índice é barato (poucos tokens) e já diz onde está cada coisa |
| Esquema dinâmico (categoria + atributos no banco, view por categoria) | serve para qualquer sistema sem código novo; o VTT consulta como tabela |
| Camada canônica (`efeito_sobrenatural`, `nivel`, `execucao`…) | magia/ritual, círculo/nível etc. são nomes diferentes para a mesma mecânica |
| Dados (3d6+2) validados fora do LLM | determinístico, verificável e é o que o VTT precisa para rolar |
| Saída estruturada (JSON Schema) nos dois provedores | formato garantido e validado pelo Pydantic |
| Gemini como padrão, Claude como opção | Gemini tem uso gratuito e é o da disciplina; trocar de provedor permite comparar custo/qualidade no gold set |
