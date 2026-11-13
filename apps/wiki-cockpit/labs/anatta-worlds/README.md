# Laboratório Anatta Worlds

Este diretório contém três gramáticas visuais comparáveis, acessíveis somente
pela rota explícita `/prototype/anatta-worlds`. Ele fica fora de `src/` porque
cada variação possui um `Canvas` próprio e isolado para pesquisa; nenhuma delas
coexiste com o `SystemScene` da aplicação ou altera o contrato de cena única da
Wiki Viva.

O estado semântico, a missão, o gate humano, o recibo e a mutação localizada são
compartilhados entre as três variações. O laboratório é compilado e tipado, mas
não deve ser promovido para a experiência principal sem que uma direção seja
escolhida e reimplementada sobre a arquitetura de produção.

O variant `organism` agora hospeda uma única bacia como beauty slice, em vez do
walking skeleton do mundo inteiro. Ele usa câmera hero autorada, assets PBR
locais, vegetação instanciada, rio animado e uma Casa da Hidrografia first-party
realmente entrável. A prova funcional e de orçamento está atual, mas o gate
visual continua reprovado diante da referência principal; veja o
[QA do beauty slice](../../../../docs/wayfinder/imersao-integrada/beauty-slice-qa.md).

O variant `sand` é um spike visual isolado de planeta inspirado no projeto open-source
[TIDEWRIGHT](https://github.com/winchxyz/tidewright) (MIT). Ele transfere para a
fixture Aurora apenas a direção material — heightfield esférico contínuo, areia
seca e úmida, microbrilho e luz rasante — sem copiar o simulador. A modelagem
interativa do spike é deliberadamente visual: não implementa solver granular,
ângulo de repouso nem conservação de volume, e portanto não deve ser descrita
como física de areia validada.
