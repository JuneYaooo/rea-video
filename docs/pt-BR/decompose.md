> Tradução para pt-BR do original em chinês ([docs/decompose.md](../decompose.md)), feita por Victor Pimenta.

# Método de decomposição: como descobrir "como um plano foi feito"

Objetivo: para cada plano, dizer como a imagem de base foi produzida, quais camadas estão sobrepostas, quais são as evidências e qual a confiança, e depois sugerir uma rota de recriação.

## 1. Classificação

| Rótulo | Significado | Rota de recriação (rea_video/capabilities/routing.yaml) |
|---|---|---|
| `live_action` | Filmado de verdade | R07: aproximar com imagem para vídeo por IA, ou filmar de novo |
| `ai_video` | Vídeo gerado por IA | R07: primeiro/último frame + prompt, gerado pelo capsule-cinema |
| `avatar` | Avatar digital falando para a câmera | R03: clonagem de voz + avatar digital |
| `cg_3d` | Render 3D | R08: modelagem e render 3D, ou aproximação com primeiro/último frame por IA |
| `code_render` | Render por código/template (motion graphics, texto, UI, gráficos, cards) | R01: reconstruir em Remotion/HTML |
| `screen_capture` | Gravação de tela/print | R02: gravar a interface real |
| `still_motion` | Imagem estática + zoom/pan | R17: uma imagem + parâmetros de movimento medidos, recriação exata local |
| `static_hold` | Frame congelado | R18: uma imagem |

As camadas sobrepostas são listadas à parte: legendas, títulos, anotações de texto, grafismos e templates de layout. Um mesmo plano pode ser "vídeo de IA + legenda feita por código".

## 2. De onde vêm as evidências

A perícia determinística responde ao que dá para medir, o VLM responde ao que precisa ser entendido. A divisão é clara:

| Pergunta | Método | Confiabilidade |
|---|---|---|
| Onde tem corte | Distância de histograma HSV e diferença de pixels, com limiar adaptativo local; a área que muda precisa ser grande o bastante, um elemento que aparece de repente não conta como corte. Jump cut / corte com aproximação: salto no mesmo enquadramento dentro de um frame, bem maior que a variação dos frames vizinhos, com antes e depois estáveis; flash ou fogo que acende e volta em um ou dois frames não conta. Fusão (dissolve): verifica se os frames do meio são uma mistura linear dos frames das pontas e usa fluxo óptico para descartar zoom | Alta (F1=1,0 em dois vídeos com gabarito, um deles com 14 fusões de 0,25 s) |
| A imagem se mexe ou não | Proporção de frames idênticos pixel a pixel, diferença entre primeiro e último frame | Alta |
| É uma imagem só com zoom/pan | Fluxo óptico LK ajustando uma transformação de similaridade (RANSAC): muitos inliers, resíduo baixo, sem movimento local e quase nada sobrando depois da compensação de movimento | Alta |
| Textura renderizada ou filmada | Proporção de blocos 8×8 chapados, número de cores para cobrir 95% dos pixels, proporção de bordas retas horizontais e verticais, ruído de Immerkær | Alta (separa render de foto) |
| Composição 2D / animação por código | Pixels do fundo idênticos frame a frame, só uma região se mexe | Alta |
| Frame rate original | Padrão de frames repetidos (de 24 para 30 dá uns 20%, com período de 4 a 6); oscilação periódica de nitidez causada por interpolação (sem frames repetidos é só evidência fraca, porque recompressão também produz isso); nativo ≥48fps sem frames repetidos | Média-alta: modelos de geração entregam 24/25fps, celular costuma filmar a 60fps |
| Filmado, IA ou 3D | Ruído de sensor e ruído temporal, tremor de câmera na mão, impressão digital do frame rate, mais o VLM caçando falhas (dedos, texto, física, textura piscando) | Média só com o determinístico, alta com VLM |
| Metadados | Fabricante/modelo do aparelho; marcação implícita de AIGC da norma chinesa GB 45438 (Label 1/2/3 e código do provedor); C2PA; assinatura de editor/renderizador | Muito forte quando aparece; plataformas costumam apagar |
| Camadas sobrepostas | Aglomerados de bordas com pixels congelados enquanto o fundo se mexe, mais a trilha de texto do OCR (posição, se muda com o tempo, se é horizontal) | Média-alta |
| Áudio | Ataques/batidas, proporção de cortes que caem em ataques (corte no beat), características de modulação da fala | Média |

Os trechos ligados por jump cut vêm do mesmo material cortado (mesmo enquadramento, mesmo fundo). Com VLM ligado, eles são juntados num clipe só e perguntados uma vez (no máximo 12 segundos e 8 trechos): o modo de produção e a forma de filmar são respondidos uma vez para o bloco inteiro, e a descrição e o prompt de recriação de cada trecho vêm separados. Quando há limite de chamadas ao VLM, a prioridade vai para os planos em que a ferramenta tem mais dúvida e para os mais longos. O texto na tela de cada plano vem direto da passada de OCR do vídeo inteiro naquele intervalo; só quando essa passada fica esparsa demais (vídeos longos) ou a camada de finalização está desligada é que ele lê de 1 a 4 frames por conta própria, conforme a duração do plano.

## 2.1 Material real do usuário

A origem do material cai em quatro tipos: gerado por IA, renderizado pelo produtor, material real do usuário e misto.

- **Quadro inteiro**: deduzido do rótulo da imagem de base. Filmado = material filmado; gravação de tela = gravação/print de interface; frame congelado cuja origem é foto ou print = material real.
- **Embutido** (só detectado dentro de imagens renderizadas):
  - Painel claro e pouco saturado com ≥6 blocos de texto pequeno num único frame → print de interface (com certeza material real)
  - Região com alta entropia em tons de cinza e sem cor chapada → imagem ou trecho de vídeo (se é real ou IA fica **a confirmar**)
  - A faixa das legendas não entra na detecção
- No plano de recriação, todo material real fica listado em `user_assets`: na recriação quem fornece é o usuário, não dá para gerar com modelo.

## 2.2 Som

Aplica HPSS sobre a STFT (filtro de mediana separando componentes harmônicos e percussivos):

- **Voz**: modulação silábica de 3 a 8 Hz na faixa da voz, mais as pausas entre frases; a frequência fundamental dá a pista de voz masculina ou feminina.
- **Música**: uma base musical tonal que continua forte nos intervalos da fala, ou um período de batida bem marcado; o BPM sai da autocorrelação dos ataques, a tonalidade do perfil de Krumhansl e as mudanças de seção da novidade cromática.
- **Edição**: proporção de cortes que caem na batida ou em ataques.
- **Efeitos sonoros**: a camada determinística só aponta transientes fortes fora da voz como candidatos de baixa confiança; a lista completa vem do que o VLM escuta (veja os testes em eval/RESULTS.md).
- **Saídas**: `audio` (medições), `audio_plan` (trilhas de som e plano de recriação já com o VLM) e `audio.png` (linha do tempo).

## 3. Fusão

Probabilidade final ∝ probabilidade determinística^(0,6 × peso de confiabilidade) × probabilidade do VLM, com duas restrições rígidas:

- Um plano com imagem congelada não pode ser classificado em nenhuma categoria de "vídeo gerado".
- Um plano com zoom/pan rígido da imagem inteira não pode ser classificado como filmado nem como avatar.

Pesos de confiabilidade: frame congelado 1,6, imagem estática com zoom/pan 1,4, render por código 1,0; filmado, IA e 3D ficam em só 0,6, então essas três categorias são decididas principalmente pelo VLM.

Quando há uma fonte visual (VLM ou revisão do agent), a decisão vem em duas etapas: primeiro, de onde a imagem veio (gerada: vídeo de IA + avatar; renderizada: 3D + código; filmada; gravação de tela; imagem estática); depois, a subcategoria dentro desse grupo, e a confiança é a probabilidade total do grupo. Assim, se a ferramenta diz vídeo de IA, o agent diz avatar e o VLM diz filmado, os dois primeiros votos somam como "gerado" e não são derrotados um a um por um "filmado" forte. Só com a ferramenta, continua valendo a subcategoria mais alta direto: a nota que a ferramenta dá para avatar é tirada do vídeo de IA, e juntar os dois passaria por cima do filmado (no conjunto de avaliação de vídeos falados para a câmera isso derrubou de 0,51 para 0,33).

Regra da maioria: quando a primeira opção da ferramenta concorda com exatamente uma das duas fontes visuais (mesma subcategoria ou mesmo grupo), o veredito tem que ficar dentro desse grupo.

Outros filtros:
- Se ferramenta e VLM discordam sobre ser filmado ou não, e nenhum agent revisou, o plano é marcado como "divergente" e entra na lista obrigatória do `review_tasks.json`: o VLM inventa evidências que não estão lá (no vídeo original do copo liquidificador, um "relógio de parede com números embaralhados").
- O frame rate só prova que o material é de origem 24fps: se foi classificado como vídeo de IA, não tem marcação de AIGC e a fonte visual acha que é filmado, o plano é marcado como "IA ou câmera filmando em 24p, a confirmar", com confiança limitada a 0,7.
- Texto lido pelo OCR que não aparece na lista de textos de pós-produção do VLM (ou o mesmo texto que acompanha um objeto em movimento na cena) conta como texto do objeto, não como camada sobreposta.

## 4. Saídas

```
out/<name>/
  breakdown.json   Video IR (rea_video.breakdown.v1): features, evidências, probabilidades, camadas sobrepostas e plano de recriação de cada plano
  report.html/md   Relatório para gente ler (mesmo conteúdo, o HTML é renderizado do Markdown): veredito → conteúdo e estrutura (resumo, gancho, linha do tempo da estrutura, roteiro) → personagens, cenários e objetos →
                   som (um card para voz / trilha / efeitos sonoros / som ambiente) → forma de filmar, iluminação e edição → camada de finalização → plano de recriação (com lista de material real e de referência) →
                   tabela de decupagem → pontos de incerteza → apêndice (perícia por plano recolhida, metadados). Personagens, cenários, objetos e roteiro vêm da análise do vídeo inteiro pelo VLM ou da revisão visual do agent (cast no topo do review_answers.json)
  storyboard.jpg   Visão geral da decupagem (colorida por modo de produção)
  shots/           Folha de contato, primeiro e último frame de cada plano (primeiro e último frame também são entrada da recriação)
  clips/, vlm_cache/  Clipes de entrada e cache do VLM (só com --vlm)
```

O `finalize()` consegue reclassificar usando só as features e respostas do VLM já salvas: quando as regras mudam, não precisa decodificar o vídeo de novo, e o `rea-video eval` faz isso automaticamente.
