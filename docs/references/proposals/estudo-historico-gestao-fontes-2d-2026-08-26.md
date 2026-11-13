# Estudo histórico: gestão 2D de fontes

Este estudo resume propostas de 26/08/2026 registradas nos commits locais
`ac3893e90` e `db99ba22c`. É um derivado textual sanitizado: as imagens e os
identificadores das fontes originais não acompanham este documento. As alternativas são
históricas e não comprovam direção atual, implementação ou aceite de produto.

## Princípios propostos

A fonte é o objeto central da tarefa. A navegação geral da aplicação deve ser
distinta das funções locais da fonte selecionada. A interface pode permitir
localizar e comparar fontes e seus recortes, mostrando configuração, escopo,
frequência, privacidade, acesso e próximo passo de forma legível. Credenciais
devem aparecer apenas como referências, nunca como valores.

Validação de configuração, autorização efetiva e disponibilidade de execução
são fatos distintos. Antes de atualizar, a interface deve explicitar o que será
lido; durante a execução, deve apresentar etapas, progresso, bloqueios e ações
possíveis com base em evidência real. Seleção, configuração, marcador de
processamento, registro de leitura, comprovação, proposta e integração também
devem permanecer distintos. Uma agenda vencida não demonstra execução.

Rótulos textuais, cores consistentes e números com origem e unidade ajudam a
explicar o estado, sem simular telemetria ou alegar resultados não observados.

## Alternativas examinadas

A primeira rodada explorou três ênfases: um console com lista, detalhe e
preparação simultâneos; um registro voltado à comparação com detalhe progressivo;
e um workspace centrado nas etapas, artefatos e encerramento de uma execução.
Uma preocupação era evitar que a navegação global se confundisse com as funções
da fonte.

A segunda rodada reorganizou essas funções como workspace da fonte, painel de
detalhe contextual ou monitor de execução dentro da fonte selecionada. A
comparação sugeria avaliar a clareza do objeto central, a distinção entre lista,
abas e execução, o próximo passo e os limites reais da automação.

## Limites deste registro

Os textos históricos não estabelecem requisitos completos de acessibilidade,
responsividade, tratamento de erros, confiabilidade de métricas ou retenção.
Regras operacionais, privacidade, autorização e capacidades precisam ser
conferidas nas fontes vigentes antes de qualquer implementação ou publicação.
Este estudo não preserva nem autoriza o uso das imagens originais.
