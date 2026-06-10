# Skills

Skills portaveis do kit (`wiki-*`), genericas e sem nomes pessoais — copiaveis
para outro repo sem ajuste profundo.

## Kit reutilizavel (`wiki-*`)

- `wiki-memory-router` — carrega a wiki e roteia contexto.
- `wiki-ingestion-agent` — fonte -> evento normalizado -> proposta.
- `wiki-llm-context-agent` — executa a passagem LLM contextual (delegada ao agente
  que roda o repo) e grava o resultado no cache.
- `wiki-operation-compiler` — mantem o cockpit [memorias/operacao.md](../memorias/operacao.md).
- `wiki-source-auditor` — rastreabilidade de fontes.
- `wiki-privacy-publication` — separa privado de publico.
- `wiki-raw-drive` — busca/baixa fontes raw de uma pasta unica do Drive (raw nunca
  e versionado).

## Perfil local por repo

Cada repo que adota o kit pode adicionar suas proprias skills especificas (perfil
local, ex.: prefixo `repo-*` ou `<nome>-*`) ao lado das `wiki-*`. Mantenha o perfil
local separado para o kit continuar copiavel.
