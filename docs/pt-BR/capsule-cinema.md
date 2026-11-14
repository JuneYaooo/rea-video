> Tradução para pt-BR do original em chinês ([docs/capsule-cinema.md](../capsule-cinema.md)), feita por Victor Pimenta.

# Integração com o capsule-cinema

O `remake-run` e o `capsule-draft` rodam os scripts do pacote `rea_video/integrations/run_remake.py` e `to_capsule.py` usando **o ambiente Python do próprio capsule-cinema** (eles fazem import de `lib/` e `scripts/` do capsule-cinema e leem o `.env` dele). O interpretador é procurado nesta ordem: `--python` > `$CAPSULE_CINEMA_PYTHON` > `<capsule-root>/.venv/bin/python`. O rea-video em si só depende de numpy/opencv/pillow/pyyaml.

```bash
CC=~/code/github/capsule-cinema          # repositório do capsule-cinema

# 1) Decompor (recomendado com VLM, reaproveitando a config do Gemini do capsule-cinema)
rea-video --env-file $CC/.env decompose ref.mp4 -o out/ref --vlm

# 2a) Gerar o rascunho de cápsula (sem mexer no código do capsule-cinema; a decomposição do rea-video entra pelo tool_factory)
rea-video capsule-draft out/ref/breakdown.json \
    --capsule-root $CC --capsule-name my_ref_remake            # só grava em capsules/ com --write-capsule

# 2b) Recriar os planos de IA: gerar tarefas → capsule-cinema gera → remonta na linha do tempo original e gera o comparativo
rea-video remake-plan out/ref/breakdown.json --capsule-root $CC --engine seedance2.0
rea-video remake-run out/ref/remake/jobs.json --dry-run   # confere as tarefas antes
rea-video remake-run out/ref/remake/jobs.json             # chamada de verdade (gera custo)
rea-video assemble out/ref/breakdown.json out/ref/remake/results.json
```

- Planos de vídeo de IA / 3D / filmados / avatar: por padrão usam o **primeiro e último frame + prompt do VLM** do plano original numa geração `first_last_frame` (`--mode image_to_video` usa só o primeiro frame).
- Imagem estática com zoom/pan e frame congelado: nenhum modelo é chamado; o `assemble` reconstrói localmente com os parâmetros de zoom/deslocamento medidos.
- Planos de render por código e de gravação de tela: por padrão mantêm o original (`keep_original`); para reconstruir, use Remotion seguindo a trilha de texto/layout do relatório.
- Recriar só alguns planos: `remake-run ... --only 2,5` (também aceita id de plano: `--only shot_002,shot_005`). Se algum plano não gerar vídeo, o comando sai com código diferente de 0, e os detalhes da falha ficam no results.json.
- Se o capsule-cinema não estiver no caminho padrão (`~/code/github/capsule-cinema`), rode uma vez `rea-video prefs capsule_root <caminho>`; ou passe `--capsule-root` toda vez, com o mesmo valor no `remake-run` e no `remake-plan`. Se o caminho gravado no jobs.json não bater, a execução é recusada.
