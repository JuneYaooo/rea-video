> Tradução para pt-BR do original em chinês ([docs/what-it-detects.md](../what-it-detects.md)), feita por Victor Pimenta.

# O que ele consegue decompor

## Como a imagem foi feita

Cada plano é classificado em uma destas 11 categorias. "A ferramenta mede" quer dizer que dá para decidir offline, sem olhar a imagem; o resto depende de um modelo de visão ou de um agent olhando o quadro.

| Categoria | Exemplos comuns | A ferramenta mede | Vídeos na avaliação |
|---|---|---|---|
| Filmado | Vídeo falando para a câmera, vlog, publi de produto, review de lugar | ✓ | 5 |
| Vídeo gerado por IA | Texto para vídeo / imagem para vídeo, microdrama de IA | ✓ | 24 |
| Avatar digital | Um retrato animado por uma voz | Em parte | 0 |
| Render 3D | Divulgação científica e animação de produto em Blender / C4D | ✓ | 14 |
| Animação 2D | Desenho à mão, Live2D, animação de personagem no AE | ✗ olhar a imagem | 0 |
| Stop motion | Massinha, feltro, bonecos de papel fotografados quadro a quadro | ✗ olhar a imagem | 0 |
| Trecho de filme/série | Imagens de filme / série / microdrama inseridas em vídeos de análise, edits e compilados de cenas famosas | ✗ olhar a imagem (a ferramenta só dá pistas) | 8 |
| Código / template | Animação de texto, UI, gráficos, cards estilo slide | ✓ | 16 |
| Gravação de tela / print | Uso de software, páginas web | ✓ | 11 |
| Imagem estática com zoom/pan | Uma imagem com zoom e deslocamento | ✓ | 3 |
| Frame congelado | Imagem ou card parado | ✓ | 5 |

No mesmo plano ainda são marcados à parte:

- Sobreposições de pós-produção: legendas, textos decorativos, títulos, grafismos, templates de layout. Texto que está nos objetos (embalagem, letreiro) é separado das legendas sempre que possível. Detalhes em "Camada de finalização", mais abaixo.
- Material real: gravações de tela, prints, fotos e trechos de vídeo embutidos na imagem; na recriação, use os arquivos originais. Produtos, logos e pessoas dentro de imagens de IA entram como imagens de referência para a recriação.
- Tratamento por IA sobre imagem filmada (decidido olhando a imagem): troca de rosto, sincronia labial, restilização, troca de roupa por IA, recorte e troca de fundo, inclusão ou remoção de objetos, filtro de beleza. O plano de recriação fica assim: "filme primeiro, depois aplique tal tratamento de IA, com tal modelo".

## Como o material filmado foi filmado

| Aspecto | O que sai |
|---|---|
| Enquadramento | Tamanho do plano (de plano geral a superclose), altura da câmera, composição |
| Câmera | Na mão / estabilizador / tripé, zoom, travelling, panorâmica, celular ou câmera, câmera lenta / timelapse / variação de velocidade |
| Iluminação | De que lado e de que altura vem a luz principal; contraste de luz; luz suave ou dura; temperatura de cor; desfoque de fundo; contraluz de recorte, brilho no olho, luminárias visíveis no quadro |
| Esquema de luz | 12 tipos, com lista de equipamento: luz frontal suave, principal + preenchimento, luz lateral dura, contraluz, luz ambiente noturna, low key, high key, luz colorida de clima (RGB / neon), still de produto, sol direto externo, externa nublada, externa em contraluz |
| Cor | Estilo (natural, teal & orange, estilo japonês, filme, preto e branco, escuro, saturado) e também saturação, contraste, nível de preto, quente ou frio |
| Edição | Ritmo, jump cut, corte com aproximação, proporção de inserts, se corta na batida |
| Formato | Falando para a câmera, filmagem de mesa, produto na mão, vlog |

Contraste de luz, suave ou dura, temperatura de cor e correção de cor saem da medição dos pixels; qual é a fonte de luz, se tem contraluz de recorte, se é externa e qual a velocidade de filmagem vêm de olhar a imagem. O relatório mostra os dois resultados lado a lado.

## Camada de finalização

O vídeo inteiro é decomposto numa linha do tempo única, sem quebrar por plano (uma frase de legenda ou um sticker muitas vezes atravessa um corte).

| Item | Como mede | Resultado |
|---|---|---|
| Linha do tempo das legendas | OCR a 2 frames por segundo, rastreando frase a frase o texto na mesma posição, e depois alinhando início e fim em uns 0,1 segundo com frames em tons de cinza a 10 por segundo; legendas de duas linhas viram uma frase só | `packaging/subtitles.srt` |
| Estilo do texto | Medido nos pixels: cor da letra, cor e espessura do contorno, cor da caixa de fundo, degradê, palavra-chave em outra cor (dá para ver até quando muda de cor na hora em que é falada), tamanho, inclinação, peso | Coluna de estilo no relatório |
| Tipo de texto | Legenda (frases trocando seguidas na mesma posição), texto decorativo (pelo menos dois destes: letra grande / colorida / inclinada / contorno grosso / várias cores / entrada com pop), título (fixo no topo), anotação de texto (cartela de capítulo, etiqueta que acompanha um objeto), texto da cena | Tipo de cada texto |
| Entrada / saída | Aparece direto, pop com escala, fade in, desliza, letra por letra; se tem pulo ou troca de cor no meio da frase | Animações no relatório e no ASS |
| Sticker / GIF / picture-in-picture | Bloco com borda nítida que fica parado sobre uma imagem em movimento; tudo muda no corte e ele não; aparece e some inteiro no meio de um plano (em material filmado isso só marca "suspeito"); se mexe por dentro com período fixo, é GIF em loop | Tempo, posição, recorte (`packaging/sticker_XX.jpg`). Na prática pega mais ou menos a metade; o resto fica para a revisão visual |
| Efeito sonoro no tempo | Cada efeito é alinhado ao evento visual mais próximo (legenda / texto decorativo / sticker aparecendo, corte, ±0,2 segundo); sem VLM, procura transientes nos momentos em que texto decorativo e sticker aparecem e lista como candidatos de baixa confiança | Coluna "imagem correspondente" da tabela de efeitos |

Também exporta `packaging/overlays.ass` (com cor, contorno, posição e animação de pop; dá para queimar direto com `ffmpeg -vf ass=`, só trocando a fonte pela do original) e `packaging/timeline.json`.

Qual é a fonte e o que tem no sticker não dá para medir nos pixels; isso vem do VLM ou do agent olhando a imagem. Em imagens 3D, de animação e de layout, objetos aparecem de repente por natureza, então nesses planos só contam stickers que atravessam cortes ou tocam em loop; o resto fica como "conteúdo da imagem", para confirmar olhando se precisar. Resultados da avaliação em [eval/RESULTS.md](../../eval/RESULTS.md).

## Som

- Voz: pessoa de verdade ou voz de IA, texto da locução.
- Trilha: BPM, tonalidade, seções, se foi gerada por IA ou vem de banco de músicas.
- Efeitos sonoros: tempo e tipo de cada efeito, e em qual evento visual ele cai (legenda / texto decorativo / sticker aparecendo, corte).
