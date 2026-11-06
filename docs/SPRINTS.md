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
- [ ] 2. Gold set: ~30 entradas anotadas + ~5 trechos irrelevantes, por sistema
- [ ] 3. Baseline: 1 LLM, saída estruturada, todos os chunks
- [ ] 4. Avaliação: precisão, cobertura, % indevido, tokens por entrada

## Sprint 2 — multiagente + RAG

- [ ] 5. Busca híbrida: literal (pdfscope) + semântica + glossário do sistema
- [ ] 6. Mapeador: roteamento pelo índice + descoberta de categorias/atributos
- [ ] 7. Especialistas com `buscar_trecho` (o salto agentivo)
- [ ] 8. Validador com devolução ao especialista
- [ ] 9. Baseline × multiagente no gold set → tabela de resultados

## Decisões

| decisão | motivo |
|---|---|
| Chunking pelo índice do PDF | o índice é barato (poucos tokens) e já diz onde está cada coisa |
| Esquema dinâmico (categoria + atributos no banco, view por categoria) | serve para qualquer sistema sem código novo; o VTT consulta como tabela |
| Camada canônica (`efeito_sobrenatural`, `nivel`, `execucao`…) | magia/ritual, círculo/nível etc. são nomes diferentes para a mesma mecânica |
| Dados (3d6+2) validados fora do LLM | determinístico, verificável e é o que o VTT precisa para rolar |
| Saída estruturada (JSON Schema) nos dois provedores | formato garantido e validado pelo Pydantic |
| Gemini como padrão, Claude como opção | Gemini tem uso gratuito e é o da disciplina; trocar de provedor permite comparar custo/qualidade no gold set |
