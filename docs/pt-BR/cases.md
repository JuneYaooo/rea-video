> Tradução para pt-BR do original em chinês ([docs/cases.md](../cases.md)), feita por Victor Pimenta.

# Casos

Os 7 casos rodaram o fluxo completo com o modelo de visão ligado, e todo plano com divergência passou pela revisão visual do agent. No mosaico, cada quadro é um plano, e a faixa colorida mostra o modo de produção, o grau de certeza e o tempo; o relatório completo traz as evidências, os prompts e o plano de recriação de cada plano.

Os vídeos de exemplo em `docs/cases/videos/` foram recomprimidos para deixar o repositório mais leve: as marcações das plataformas (Douyin / TikTok / WeChat) não foram mantidas e há uma camada extra de artefatos de compressão. Se você rodar com eles, o resultado vai diferir do relatório, ainda mais sem o modelo de visão. Para reproduzir os relatórios, use o arquivo original baixado da plataforma.

Os relatórios completos linkados aqui estão em inglês quando existe versão em inglês; só o caso 1 tem apenas o relatório original em chinês.

## 1. Original vs recriação por IA: vídeo filmado do TikTok → refeito com outro produto

21 segundos · original com 11 planos / recriação com 8 planos

![Decomposição plano a plano do original do copo liquidificador e da recriação por IA](../cases/juicer_pair.jpg)

▶ [Original do TikTok](../cases/videos/v11_tiktok_original.mp4) · [Recriação por IA](../cases/videos/v12_oiioii_juicer_remake.mp4) · Relatório completo (em chinês): [original](../cases/v11/report.md) · [recriação](../cases/v12/report.md)

| | Original | Recriação por IA |
|---|---|---|
| Como foi feito | Tudo filmado no celular, pessoa real falando | Tudo gerado por IA (o arquivo tem marcação de AIGC), locução de IA |
| Como refazer | 1 cenário, 2 posições de câmera, tudo numa bancada de uma vez | Os 8 planos juntados em 3 gerações de modelo de vídeo, com prompts |
| O que preparar | O produto de verdade | Imagem de referência do produto (com o logo do copo bem legível) |

Como foi feito:

- O original foi filmado no celular em primeira pessoa: 30fps nativo, com ruído de sensor, pessoa real falando com som direto.
- A recriação é da OiiOii, que usou o original como referência, trocou pelo copo liquidificador da Morphy Richards e refez tudo com modelo de vídeo: o arquivo tem marcação de AIGC, o logo no copo sai embaralhado e a locução é uma voz masculina de IA. Cenário, posições de câmera e o ritmo dos jump cuts foram copiados do original.

Como refazer:

- O original é organizado pela filmagem: 1 cenário, 2 posições de câmera (7 planos próximos e 4 closes), com 1 segundo de sobra antes e depois de cada take.
- A recriação é organizada pela geração: 8 planos juntados em 3 gerações (preparo, bater, servir e resultado), cada uma com a imagem de referência do produto e um trecho do original, e cada geração começa no último frame da anterior. Com um modelo que não aceita multiplano (Seedance 2.0) são 8 gerações; com o Seedance 2.5, só 3.

Prompt da primeira geração (trecho; o relatório tem a versão completa e a versão em inglês):

```text
Vertical 9:16; luz frontal suave, puxada para o frio, fundo desfocado. A aparência do produto segue @imagem1, logo e detalhes iguais. Use @vídeo1 como referência de movimento, câmera e ritmo de edição. Corte seco entre os planos.
Plano 1 (0.0-1.8s): câmera fixa de cima, um copo liquidificador portátil azul sobre uma bancada de mármore; uma mão coloca com cuidado uma caixa transparente de morangos frescos à direita do copo e depois sai do quadro
Plano 2 (1.8-2.8s): a mão solta, alguns morangos caem dentro do copo liquidificador azul logo abaixo, câmera parada
Plano 3 (2.8-3.7s): uma mão solta pedaços de kiwi verde, que caem no copo, onde já há pedaços de morango vermelho
Plano 4 (3.7-6.2s): uma mão segura um frasco plástico branco e despeja o leite devagar no copo; o nível do líquido vai subindo
Plano 5 (6.2-9.0s): a mão encaixa e rosqueia a tampa, depois levanta o copo com uma mão só e vira de ponta-cabeça; a fruta e o leite descem
```

## 2. Vídeo misto: diálogo de personagens de IA + interface por código + gravação de tela real

19 segundos · 10 planos

![Mosaico da decomposição do vídeo misto](../cases/dual_role/storyboard.jpg)

▶ [Vídeo original](../cases/videos/dual_role.mp4) · [Relatório completo](../cases/dual_role/report_en.md)

Como foi feito: dois personagens gerados por IA conversando numa sala, um de cada vez (5 planos), intercalados com 5 trechos de interface feitos em código, que incluem 8,2 segundos de gravação de tela real e 4,8 segundos de prints; título e legendas entraram na pós.

Como refazer: os 5 planos de diálogo estão separados pelas interfaces, mas são do mesmo cenário, então uma geração só resolve (com duas imagens de referência para travar a cara dos personagens), e na edição as interfaces voltam para o lugar. Os 5 trechos de interface viram 1 projeto Remotion; gravação de tela e prints você usa os seus.

## 3. Divulgação científica em 3D: por que o ovo salgado solta óleo

67 segundos · 21 planos

![Mosaico da decomposição do vídeo científico em 3D](../cases/salted_egg/storyboard.jpg)

▶ [Vídeo original](../cases/videos/salted_egg.mp4) · [Relatório completo](../cases/salted_egg/report_en.md)

Como foi feito: os 21 planos são todos render 3D (bichinhos de pelúcia como personagens + animação em corte explicando o processo), narração com voz feminina de IA, trilha de banco de músicas, e 45% dos cortes caem na batida (cortando ao acaso daria uns 25%).

Como refazer, por dois caminhos:

- Mandar para o modelo de vídeo: os 21 planos juntados em 10 gerações.
- Pedir para um LLM escrever código em Blender ou Three.js: o personagem é modelado uma vez só, cada plano ganha sua câmera e é renderizado; é o que dá mais consistência entre ângulos, e mudar o texto é só mudar o código. Esse tipo de vídeo científico já dá para um LLM gerar hoje.

## 4. Animação de UI por código: vídeo de lançamento de produto

70 segundos · 12 planos

![Mosaico da decomposição da animação de UI por código](../cases/v10/storyboard.jpg)

▶ [Vídeo original](../cases/videos/v10_oiioii_gen_coding_first.mp4) · [Relatório completo](../cases/v10/report_en.md)

Como foi feito: vídeo de divulgação do recurso "recriação de vídeo" da OiiOii. 83% é animação feita em código (perspectiva de interface, easing de texto, logo de partículas), 12% é gravação de tela e 1 plano é print com zoom/pan; o vídeo que toca dentro da interface, o logo e os prints são material real embutido.

Como refazer: não precisa de modelo de vídeo. Vira 1 projeto Remotion, com texto e interface totalmente controláveis; mudar o texto é só mudar os dados, e dá para pedir direto para um LLM escrever. A gravação de tela você faz na sua própria interface.

## 5. Clipe musical de IA: a música foi feita por IA ou vem de banco?

165 segundos · 86 planos

![Mosaico da decomposição do clipe musical de IA (primeiros 24 planos)](../cases/qing_mv/preview.jpg)

(A imagem mostra os primeiros 24 planos) ▶ [Vídeo original](../cases/videos/qing_mv.mp4) · [Relatório completo (86 planos)](../cases/qing_mv/report_en.md)

Como foi feito: um rap gerado por IA, com todas as imagens geradas.

- Composição das imagens: 16% de avatar digital de um velho de barba branca dublando no microfone, 52% de vídeo de IA com cenários da dinastia Qing, 15% de planos em estilo 3D e 17% de imagens estáticas com zoom/pan.
- A música foi classificada como gerada por IA: a faixa inteira é contínua, a voz é cantada e termina junto com o vídeo. Na verdade foi feita no Suno, então acertou.
- O modelo de visão disse que vários planos eram "filmagem real de série"; o agent, olhando as imagens, viu que as letrinhas no memorial imperial eram pseudocaracteres que não formam palavra nenhuma e confirmou que é IA.

Como refazer:

- Primeiro gere a música no Suno, seguindo estilo e BPM.
- Nos planos de dublagem, use um retrato + a voz cantada para animar um avatar digital.
- Os demais planos de IA juntados em 34 gerações.
- Os 19 planos de imagem estática com zoom/pan são feitos localmente, sem chamar modelo.

## 6. Publi filmada: unboxing imersivo

72 segundos · 29 planos

![Mosaico da decomposição do unboxing filmado](../cases/unboxing/storyboard.jpg)

▶ [Vídeo original](../cases/videos/unboxing.mp4) (Douyin, 阿咪🍓, transcodificado em 720p) · [Relatório completo](../cases/unboxing/report_en.md)

Como foi feito: tudo filmado. Celular fixo num suporte de cima, um tapete, uma posição de câmera só; sem locução, só o som direto de abrir as embalagens e uma trilha de banco a 92 BPM; correção de cor no estilo japonês clarinho (mais luz, pouca saturação, preto levantado). Dividido por produto: cada item é desembalado e depois mostrado na mão, com média de 2,6 segundos por plano, e uma foto de todos os produtos juntos no começo e no fim.

Onde ferramenta, modelo de visão e agent discordaram:

- A transcodificação do Douyin apagou o ruído de sensor. Rodando só a ferramenta offline, 35% da duração dos planos parados de mãos vistos de cima foi classificada como IA.
- O modelo de visão (Gemini) disse que 5 planos eram gerados por IA, e um deles era só uma mão trazendo um prato listrado para perto da câmera.
- O agent olhou a folha de contato plano a plano: mesmo tapete, mesmo conjunto de produtos, texto impresso nas embalagens nítido e legível, sem deformação nem caractere embaralhado, e classificou tudo como filmado. Depois de incorporado, ficou 97% filmado, e 2 planos somando 1,9 segundo continuaram como IA na fusão; o relatório marca esses como a confirmar.

Como refazer: não precisa de modelo. Um celular + suporte de cima, luz natural de dia perto da janela, produtos espalhados sobre um tapete ou toalha clara; na hora de abrir, a mão entra pela parte de baixo do quadro e cada produto fica 2 a 3 segundos na tela; na pós, mais luz, menos saturação, uma trilha leve de banco de músicas e legendas em letra pequena ao lado de cada produto.

## 7. IA misturada com gente de verdade: gerando um vídeo de publi a partir de um vídeo seu falando para a câmera

58 segundos · 21 planos

![Mosaico da decomposição do tutorial de publi com IA](../cases/ai_daihuo/storyboard.jpg)

▶ [Vídeo original](../cases/videos/ai_daihuo.mp4) (Douyin, 晨曦的好物铺子, transcodificado em 720p) · [Relatório completo](../cases/ai_daihuo/report_en.md)

Como foi feito: 75% filmado + 25% IA.

- Parte filmada: 3 segundos falando para a câmera frontal (corredor de prédio comercial, luz ambiente de teto), 4 segundos falando com um picture-in-picture de fotos do produto por cima, e 37 segundos de demonstração filmando com câmera a tela de um celular de verdade (não é gravação de tela: dá para ver a borda do celular, a caneta touch e o reflexo da luz do teto na tela).
- Parte de IA: 13 segundos de "publi com gente de verdade" gerados no Seedance 2.0 do Jimeng, usados uma vez no começo e outra no fim (idênticos frame a frame). No próprio vídeo a autora explica o processo: o Doubao escreve o prompt → no Jimeng ela escolhe "vídeo seu falando para a câmera gravado antes" como referência de pessoa e sobe duas fotos reais da garrafinha como referência de produto → gera 10 segundos.
- Relação entre a pessoa real e a IA: a pessoa no trecho de IA foi gerada a partir do vídeo da própria autora falando para a câmera, mas sem óculos e com outra roupa, e não é a mesma filmagem dos trechos falados. As evidências são a marca d'água "即梦 @知遇" no canto inferior direito, o texto impresso em inglês na caixa de presente todo embaralhado, e a garrafinha e a caixa batendo com as fotos do produto que ela sobe depois.

Onde ferramenta, modelo de visão e agent discordaram:

- A ferramenta classificou os 37 segundos de tela de celular filmada como render 3D ou IA (os blocos de cor chapada da UI parecem imagem renderizada) e ainda classificou a fala para a câmera como IA; a confiança do vídeo inteiro ficou em só 47%.
- Os planos que o modelo de visão chamou de filmados estavam quase todos certos, mas quando o motivo dele batia de frente com a ferramenta, a fusão seguiu a ferramenta.
- O agent revisou plano a plano olhando as imagens e mudou 15 planos, chegando a 75% filmado + 25% IA, o que bate com o que a autora conta. Ainda sobrou 1 plano de 1,3 segundo de fala para a câmera que, depois da fusão, ficou como IA com 54%; o relatório marca como a confirmar.
- Os dois trechos de IA não têm marcação de AIGC no arquivo, e o `show_ai_corner` devolvido pelo Douyin também é false, então a pista da marcação da plataforma aqui não diz nada.

Como refazer: a fala para a câmera e a demonstração no celular você filma normal. Para o trecho de publi, siga o caminho da autora: use 10 segundos seus falando para a câmera como referência de pessoa e fotos reais do produto como imagem de referência, e gere no Jimeng ou no Seedance; o relatório traz o prompt desse plano em chinês e em inglês. Cuidado para a embalagem gerada não ter texto que alguém vá ler: texto embaralhado é o que mais entrega que é IA.
