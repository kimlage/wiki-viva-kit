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
