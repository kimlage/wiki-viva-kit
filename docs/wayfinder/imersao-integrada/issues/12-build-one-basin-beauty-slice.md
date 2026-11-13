# Construir uma única bacia como beauty slice

Type: prototype
Mode: HITL
Status: executável; gate visual reprovado
Branch: `wiki/anatta-worlds-beauty-slice-20260730`
Owner: Codex, 2026-07-30

## Correção de direção

As imagens existentes continuam sendo a régua. Este ticket substitui a ideia de
prototipar mais mundos completos com baixa qualidade. A pergunta agora é menor
e mais exigente:

> Uma única microbacia, construída no runtime real, consegue provar que o mundo
> visual desejado pode existir sem romper o loop de evidência, gate e receipt?

Não são permitidos novos moodboards, uma simplificação low-poly ou um dashboard
vestido de 3D.

## Por que o protótipo anterior ficou muito abaixo da referência

| Camada | Implementação anterior | Consequência visual |
| --- | --- | --- |
| câmera e composição | vista geral alta, sem planos de profundidade | mapa/diorama em vez de lugar |
| terreno | volumes suaves, cores planas e sem shoreline | massa procedural crua |
| materiais | poucas cores sem blend por inclinação, altura e umidade | ausência de geologia e escala |
| água | material emissivo uniforme e espuma sem relação causal | fita ciano, não rio |
| vegetação | primitivas repetidas em grade, sem instancing ou clusters | ruído homogêneo |
| arquitetura | caixas fechadas, sem interior ou continuidade espacial | módulo como ícone, não lugar entrável |
| luz e atmosfera | fill uniforme, pouco contraste e sem grade | relevo achatado |
| animação | `frameloop=demand` e quase nenhum movimento ambiental | mundo congelado |
| interface | painel grande sobre a cena e coordenadas CSS | dashboard cobrindo a geografia |
| orçamento | baixo custo por ausência de conteúdo, não por otimização | métrica barata sem prova visual |

O reducer compartilhado, a ordem `diff → missão → gate → receipt → mutação` e
os `dataRef` continuam válidos. A perda ocorreu no render e na integração
espacial, não no contrato semântico.

## Beauty slice implementado

O variant `organism` agora contém uma única bacia de 38 × 34 m:

- câmera hero autorada antes do dressing e OrbitControls deliberadamente
  limitados;
- heightfield de aproximadamente 55 mil triângulos com vale escavado,
  tributários e blend triplanar rocha/solo por inclinação e altitude;
- rio contínuo com duas normais animadas, poços, duas quedas, espuma causal,
  faixa de margem molhada e resposta visual à mutação autorizada;
- materiais PBR CC0, HDRI, sol direcional, sombras 2K, fog, SSAO, bloom
  localizado, color grade e vignette;
- 118 árvores fotogramétricas instanciadas em três variantes, com variação de
  escala, clusters e animação de vento;
- afloramentos, clusters de rocha e boulders fotogramétricos instanciados;
- Casa da Hidrografia autorada como GLB first-party reproduzível pelo script
  `apps/wiki-cockpit/scripts/build_anatta_module.py`, com fundação, deck,
  corrimão, degraus, abertura frontal e interior visível;
- transição de câmera para uma superfície 2D fisicamente localizada na parede
  interna, preservando seleção, fase e receipt;
- telemetria legível no próprio slice e atributos de readback para FPS, tempo de
  frame, draw calls, triângulos, geometrias, texturas e primeiro frame.

## Orçamento medido

Medição no Mac atual, viewport 1280 × 720, DPR limitado a 1,25:

| Medida | Orçamento | Leitura observada |
| --- | ---: | ---: |
| FPS sustentado | ≥55 | 60 em 10/10 amostras |
| frame médio | ≤18,2 ms | 16,7 ms |
| 1% low | ≥40 | ainda não instrumentado |
| draw calls | ≤250 | 95–96 |
| triângulos | ≤1,5 M | 1.273.525 |
| primeiro frame do Canvas | ≤8 s | 234 ms no reload verificado |
| geometrias / texturas | informativo | 88 / 55 |
| assets locais | ≤5 MiB | 3.786.441 bytes |

O asset gate registra 16 assets: 2 first-party e 14 externos, todos locais,
hashados, licenciados e sem hotlink. O valor de primeiro frame mede o Canvas
depois que o chunk foi carregado; não substitui uma medição cold-cache de rede.

## Avaliação das soluções de água

| Solução | Capacidade | Compatibilidade e licença | Decisão |
| --- | --- | --- | --- |
| [Water Pro](https://threejsroadmap.com/buy-threejs-water-pro) | FFT/JONSWAP, reflexão/refração e régua alta para oceano | comercial; Three r181+; WebGPU preferido; o código-fonte não pode entrar no repo público; rios ainda são uma direção futura/separada | não comprar como resposta automática para este rio; manter bake-off futuro para oceano |
| [Tidewater](https://gettidewater.com/) | preset de rio, shoreline foam, WebGPU e fallback WebGL2 | comercial; Three r184; fonte licenciada não pode ser publicada | candidato comercial mais aderente ao slice, em adapter privado |
| [Ekigar](https://x.com/SkyeSharkie/status/2082477926139011570) | referência visual promissora | nenhuma release, API, licença ou compatibilidade pública verificável | watchlist, não dependência |
| [Three Water2](https://threejs.org/examples/webgl_water_flowmap.html) | flow normals, reflexão e refração em Three aberto | MIT e compatível com a linha atual r170; reflexos planares não resolvem sozinhos um rio com quedas | baseline aberto e fonte das normais; o slice usa material próprio mais barato |

A separação legítima é um contrato público `WaterSystem` com três
implementações:

1. `OpenRiverAdapter`, versionado no kit e sempre disponível;
2. `TidewaterAdapter`, entregue por pacote privado e carregado apenas quando uma
   licença válida estiver presente;
3. `WaterProOceanAdapter`, reservado a cenas oceânicas e ao mesmo bake-off.

O repositório público contém o contrato, fixtures de comparação e fallback; o
código comercial permanece fora dele. Todas as opções devem renderizar a mesma
geometria, câmera, luz e estado para comparação honesta.

## Comparação visual

O comparativo combinado está em
[referência versus render real](../../../../apps/wiki-cockpit/.visual-qa/reference-vs-beauty-final.png).
O exterior e o interior reais estão em
[hero final](../../../../apps/wiki-cockpit/.visual-qa/beauty-hero-final.png) e
[interior final](../../../../apps/wiki-cockpit/.visual-qa/beauty-interior-final.png).

O resultado real deixou de ser o protótipo de primitivas anterior e prova:

- uma geografia navegável com orçamento estável;
- arquitetura realmente entrável;
- continuidade de estado 3D → 2D → consequência;
- assets, materiais, iluminação e instancing compatíveis com o runtime real.

O gate visual continua reprovado. A referência ainda é claramente superior em:

- densidade e estratificação geológica;
- erosão, sedimento e integração rocha–margem–água;
- variação hidráulica e reflexão local;
- sub-bosque, vegetação ripária e hierarquia de espécies;
- acabamento arquitetônico e integração da fundação ao leito.

Portanto este ticket não autoriza promoção, merge ou declaração de direção
visual concluída.

## Próxima vertical técnica

Antes de expandir a área:

1. substituir o heightfield matemático por terreno autorado com splatmap,
   erosion mask, macro variation e cliff meshes alinhados às normais;
2. produzir leito e shoreline como geometria autorada, com wetness e decals;
3. executar o bake-off `OpenRiverAdapter × TidewaterAdapter` sobre este mesmo
   enquadramento;
4. adicionar duas espécies de sub-bosque e uma faixa ripária, com LOD real;
5. rebakear a Casa da Hidrografia em um atlas PBR e cortar fisicamente sua
   fundação no terreno;
6. medir 1% low, memória GPU e cold-cache em hardware físico;
7. repetir o comparativo até não restar nenhum P0 visual.

## Roteiro de inspeção

Servidor:
`http://127.0.0.1:4173/prototype/anatta-worlds?variant=organism`

1. No estado inicial, confirme rio como linha-guia, módulo no terço direito,
   árvores em planos de profundidade e `budget ok`.
2. Arraste suavemente a bacia e use o scroll dentro dos limites de câmera.
3. Clique **Ver o diff** e depois **Focar a tensão**.
4. Entre na **Casa da Hidrografia** e confirme que a câmera atravessa a abertura
   sem trocar de rota ou perder a seleção.
5. Role a superfície interna, escolha **Abrir missão possível → Fazer** e siga
   até o gate humano.
6. Revise as três claims como **aceitar → corrigir → rejeitar**, emita o receipt
   e só então aplique a mutação.
7. Volte à bacia e confirme `26%`, estado `recovering`, marcador de receipt e
   mudança apenas localizada.
8. Reabra o módulo e confirme que a parede 2D mostra a consequência e o receipt.
9. Compare o hero real lado a lado com a referência. Se a primeira leitura ainda
   for “terrain demo” em vez de “paisagem”, mantenha o gate reprovado.
