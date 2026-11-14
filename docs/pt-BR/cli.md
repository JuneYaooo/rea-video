> Tradução para pt-BR do original em chinês ([docs/cli.md](../cli.md)), feita por Victor Pimenta.

# Referência da linha de comando

No dia a dia você não precisa digitar nada disso: entregue o repositório e o vídeo para o agent e ele chama os comandos seguindo o [SKILL.md](../../skills/rea-video/SKILL.md). Esta página é para quem quer rodar na mão ou entender o que o agent está fazendo.

## Instalação

Precisa de Python ≥ 3.10 e ffmpeg (macOS: `brew install ffmpeg`; Ubuntu: `apt install ffmpeg`).

```bash
git clone <este repositório> && cd rea-video
pip install -e ".[ocr]"          # numpy / opencv / pillow / pyyaml / onnxruntime + OCR opcional
rea-video --help
bash scripts/install_skill.sh    # opcional: instala a CLI e linka a skill em ~/.claude/skills, ~/.codex/skills, ~/.agents/skills
```

Se você instalar o `[ocr]` na mão, as dependências de OCR trazem junto um `opencv-python`, que briga com o `opencv-python-headless` usado pelo rea-video pelo mesmo diretório `cv2`. Depois de instalar, rode uma vez:
`pip uninstall -y opencv-python && pip install --force-reinstall --no-deps "opencv-python-headless>=4.8,<5"` (o `install_skill.sh` já faz isso sozinho).

No Claude Code dá para instalar a skill também como plugin (a CLI continua precisando de `pip install`; o primeiro passo da skill confere isso):

```text
/plugin marketplace add JuneYaooo/rea-video
/plugin install rea-video@rea-video
```

Na primeira decomposição ele baixa automaticamente um modelo de separação de voz de uns 67 MB (`~/.cache/rea-video/models`). Um vídeo de 30 segundos sem VLM fica pronto em cerca de 1 minuto.

Com a skill instalada, é só falar no Claude Code / Codex / zcode algo como "decompõe esse vídeo xxx.mp4 e me diz se foi feito com IA". O agent segue o fluxo do [SKILL.md](../../skills/rea-video/SKILL.md): consulta a memória, decompõe, revisa olhando as imagens e entrega no formato do template.

## Primeiros passos

```bash

# 1. Só a perícia determinística (offline, de graça)
rea-video decompose ref.mp4 -o out/ref

# 2. Com VLM (recomendado, não obrigatório): um modelo multimodal olha a imagem e acerta mais em filmado/IA/3D
#    Serve qualquer modelo multimodal compatível com OpenAI; dá para listar vários como fallback
export REA_VLM_BASE_URL=https://.../v1 REA_VLM_API_KEY=... REA_VLM_MODEL=gemini-2.5-pro,gpt-4o
rea-video decompose ref.mp4 -o out/ref --vlm
#    Ou reaproveitando a config do capsule-cinema: rea-video --env-file ~/code/github/capsule-cinema/.env decompose ref.mp4 -o out/ref --vlm
#    Se todas as chamadas ao VLM falharem, nada é interrompido; o relatório e a linha "VLM:" do `rea-video summary` avisam que todas falharam e que o resultado equivale a rodar sem VLM

open out/ref/report.html

# 3. Sem VLM, mas com um agent que enxerga imagem (zcode, Claude Code e outros agents multimodais): o agent faz o papel de VLM
rea-video review out/ref             # gera as tarefas de revisão por plano e o template de respostas
rea-video apply-review out/ref --by zcode   # depois que o agent preenche as respostas, incorpora ao veredito e ao relatório

# 4. Correções e preferências do usuário ficam guardadas (em ~/.rea-video; mude o local com REA_VIDEO_HOME)
rea-video correct out/ref --shots 3 --label still_motion --note "isso é stop motion"
rea-video prefs vlm on && rea-video prefs --note "relatório o mais curto possível"
rea-video memory

# Só separar o áudio: stems/original.wav (som original), vocals.wav (voz limpa), music.wav (trilha)
rea-video stems ref.mp4 -o out/ref
```

Exemplo de saída de um vídeo misto (no idioma padrão, chinês; com `--lang pt-BR` o mesmo resumo sai em português). Em resumo: render por código/template 59% + vídeo gerado por IA 41%, com legendas e título sobrepostos; o plano 1 vai para a rota R01 (reconstruir em Remotion) e o plano 2 para a R07 (geração por primeiro/último frame no capsule-cinema):

```
结论：混合制作：代码/模板渲染 59% + AI 生成视频 41%；叠加层：字幕、标题（代码/剪辑软件合成）
#1 00:00.000 1.38s 代码/模板渲染 → R01 Remotion 重建
#2 00:01.375 2.50s AI 生成视频（24fps 源、无传感器噪声…）→ R07 首尾帧生成（capsule-cinema）
...
```

## Recriando junto com o capsule-cinema

```bash
CC=~/code/github/capsule-cinema   # repositório do capsule-cinema; também dá para definir CAPSULE_CINEMA_ROOT, ou rodar uma vez rea-video prefs capsule_root $CC e não precisar mais do --capsule-root
rea-video remake-plan out/ref/breakdown.json --capsule-root $CC                  # planos de IA → tarefas de geração por primeiro/último frame
rea-video remake-run out/ref/remake/jobs.json                                    # chama o capsule-cinema para gerar (é cobrado; teste antes com --dry-run)
rea-video assemble out/ref/breakdown.json out/ref/remake/results.json            # remonta na linha do tempo original + vídeo comparativo; com --overlays recoloca legendas e textos decorativos nos planos trocados
rea-video capsule-draft out/ref/breakdown.json --capsule-root $CC --capsule-name my_remake
```

- Imagem estática com zoom/pan e frame congelado: nenhum modelo é chamado; a reconstrução é feita localmente e com precisão usando os parâmetros de zoom e deslocamento medidos.
- Render por código e gravação de tela: o relatório traz a trilha de texto e o layout para você refazer em Remotion.
- Legendas, textos decorativos e stickers: não entram no prompt de geração. Se o frame de referência de um plano tiver a legenda original, o `remake-plan` avisa para apagar antes; depois de gerar, recoloque tudo com `assemble --overlays`.
- `capsule-draft`: injeta a decomposição pelo `tool_factory` que já vem no capsule-cinema e gera um rascunho de receita reaproveitável, sem mexer no código do capsule-cinema.

Veja [capsule-cinema.md](capsule-cinema.md).

## Comandos

| Comando | O que faz |
|---|---|
| `decompose VIDEO [--vlm] [--no-ocr] [--ocr-lang zh\|ja] [--lang zh\|en\|pt-BR] [--no-packaging]` | Decompõe o vídeo e gera breakdown.json, report.html/md, storyboard.jpg, primeiro e último frame de cada plano, além de `packaging/` (legendas SRT, ASS com estilo, linha do tempo da finalização, recortes dos stickers). `--lang` define o idioma do veredito, do relatório, da saída do `summary` e das descrições do VLM: `zh` (padrão), `en` ou `pt-BR` (relatório em português do Brasil; as respostas em texto livre do VLM também voltam em português, mas os prompts de geração de imagem e vídeo continuam em inglês, porque é em inglês que os modelos de geração funcionam melhor). O agent escolhe conforme o idioma da pergunta do usuário, e `rea-video prefs lang pt-BR` deixa como padrão. Os nomes de campo `*_zh` no breakdown.json continuam iguais, mas o conteúdo segue o idioma do relatório. `--no-packaging` pula a camada de finalização (economiza uns 30 a 50 segundos por minuto de vídeo). `--ocr-lang ja` usa o modelo de reconhecimento de japonês para ler legendas e textos decorativos (no primeiro uso baixa uns 10 MB para `$REA_VIDEO_MODELS`; offline, aponte `$REA_OCR_REC_MODEL` para um modelo local), e `rea-video prefs ocr_lang ja` deixa como padrão |
| `review OUT_DIR` | Gera, para um agent que enxerga imagem, as tarefas de revisão plano a plano (review_tasks.json) e o template de respostas (review_answers.json) |
| `apply-review OUT_DIR [ANSWERS] [--by NAME] [--lang zh\|en\|pt-BR]` | Junta as respostas da revisão visual do agent com o resultado determinístico e reescreve o breakdown.json e o relatório. Com `--lang` dá para trocar o idioma do relatório nesta etapa (veredito, evidências e texto do relatório são gerados de novo; descrições e prompts que o VLM já escreveu ficam no idioma original) |
| `correct OUT_DIR --shots N --label L [--real yes/no] [--note]` | O usuário aponta um erro: corrige o veredito e o relatório e grava na memória (da próxima vez aplica sozinho ao mesmo arquivo e avisa na revisão de planos parecidos) |
| `prefs [KEY VALUE] [--note TEXT]` | Preferências do usuário: engine padrão, VLM ligado por padrão ou não, arquivo de config do VLM, nome do revisor, idioma do relatório (`lang zh\|en\|pt-BR`) e instruções em texto livre para o agent |
| `memory [--export-labels YAML]` | Mostra o que ficou guardado (preferências, tipos de correção mais comuns); exporta as correções como amostras de avaliação |
| `probe VIDEO` | Só olha as pistas dos metadados (aparelho que filmou, marcação implícita de AIGC, C2PA, assinatura de editor) |
| `summary breakdown.json` | Imprime o veredito de forma compacta e marca os planos de baixa confiança que precisam de revisão |
| `tiles VIDEO --start --end --every` | Extrai frames por tempo e monta um mosaico para revisar de perto |
| `eval labels.yaml` | Mede a acurácia e o F1 dos pontos de corte em amostras anotadas |
| `capsule breakdown.json` | Exporta o JSON de análise de vídeo do capsule-cinema |
| `remake-plan` / `assemble` | Gera as tarefas de recriação e remonta o vídeo final |
| `remake-run JOBS [--dry-run] [--only 2,5\|shot_002] [--capsule-root]` | Executa as tarefas de recriação com o capsule-cinema (é cobrado); se algum plano não gerar vídeo, sai com código diferente de 0 |
| `capsule-draft breakdown.json` | Gera um rascunho de cápsula do capsule-cinema |

## Fluxo de trabalho (meta de design; hoje vai até a decomposição e a recriação dos planos de IA)

```
Ingest ─► Decompose ─► Video IR ─► Plan ─► Reconstruct ─► Verify ─► Remix
 importar  decupar      código-fonte roteamento reconstruir  verificar  reescrever em lote
```

| Etapa | Status |
|---|---|
| Ingest, Decompose, Video IR (`breakdown.json`) | Funcionando, é o núcleo deste repositório |
| Plan | Funcionando: cada plano ganha uma rota de recriação; planos de IA viram tarefas do capsule-cinema |
| Reconstruct | Em parte: planos de IA vão para o capsule-cinema e imagens estáticas com zoom/pan são reconstruídas localmente; na camada de código só sai a trilha de texto e o layout, ainda não gera o projeto Remotion |
| Verify | Em parte: o `assemble` remonta o vídeo e gera um comparativo; a nota automática ainda não existe |
| Remix | Não começou |

1. **Ingest (importar)**: probe, extração de frames, separação das trilhas de áudio.
2. **Decompose (decupar)**: CV determinística e VLM dividem o trabalho. A CV cuida de tempo e posição exatos: cortes, trajetória do OCR, segmentação, movimento de câmera, batidas, alinhamento palavra a palavra. O VLM cuida da semântica: intenção do plano, atuação, estilo.
3. **Video IR (código-fonte)**: linha do tempo → trilhas → clipes. Cada clipe é marcado com o modo de render (`code` / `gen` / `footage` / `audio`) e traz parâmetros, evidências e unknowns.
4. **Plan (roteamento)**: lê o [mapa de capacidades](../../rea_video/capabilities/README.md), roteia cada unidade de geração para uma primitiva e um modelo e produz uma Shot Recipe com estimativa de custo e os pontos que precisam da confirmação do usuário.
5. **Reconstruct (reconstruir)**: a camada de código renderiza com Remotion e afins, a camada de geração chama modelos, a camada de áudio usa TTS, música e efeitos sonoros, e no fim tudo é composto.
6. **Verify (verificar)**: confere alinhamento dos cortes, consistência do texto do OCR, IoU do layout, similaridade perceptual, consistência do personagem, trajetória de movimento, batidas e sincronia labial, gera um scorecard e o agent fica em loop corrigindo os planos com pior nota.
7. **Remix (reescrever)**: para trocar pessoa, produto, texto, idioma ou formato de tela, renderiza de novo só as camadas afetadas.

## Dois modos

- **fidelity (recriação fiel)**: o objetivo é bater estrutura, ritmo, movimento de câmera, texto e animação item por item, medido em nota.
- **adapt (adaptação criativa)**: mantém o "porquê funciona" do original, como gancho, revelação e ritmo, e reescreve o conteúdo para o tema novo.

Os dois modos podem ser misturados por camada. Por exemplo, ritmo e câmera em fidelity, personagens e texto em adapt.
