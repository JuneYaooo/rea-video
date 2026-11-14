> Tradução para pt-BR do original em chinês ([docs/replicate.md](../replicate.md)), feita por Victor Pimenta.

# Recriando a partir do relatório

O relatório diz como cada plano foi feito, e cada tipo de produção pede um próximo passo diferente. É comum um vídeo misturar vários tipos: trate cada um como explicado abaixo e, no fim, peça para o agent montar tudo na linha do tempo original.

## Planos filmados: filme você mesmo

1. O relatório traz a ordem do dia: quantos cenários, quantas posições de câmera em cada um e por qual começar; o enquadramento, se é na mão ou no tripé, de onde vem a luz principal, se precisa de luz de preenchimento, além da lista de equipamento. Planos do mesmo cenário ficam juntos na ordem de filmagem, mesmo que apareçam separados no vídeo final.
2. Filme seguindo a ordem do dia, mande o material para o agent e diga "encaixa o que eu filmei seguindo a decupagem".
3. O agent corta cada take na posição e duração do plano correspondente, monta na linha do tempo original e gera um vídeo comparativo lado a lado com o original, para você conferir se o ritmo bateu. Planos que você ainda não filmou ficam com o original no lugar, então dá para filmar uma cena e já conferir.

## Planos gerados por IA: mande para o modelo de vídeo

1. O relatório traz as unidades de geração: planos seguidos do mesmo cenário viram uma geração só, com o modelo indicado, as imagens de referência que você precisa preparar (foto do produto, foto da pessoa), o prompt multiplano (em chinês e em inglês) e como emendar uma geração na seguinte.
2. Tem dois jeitos:
   - Manual: cole o prompt da unidade e as imagens de referência em sites como Jimeng (Dreamina) ou Kling, gere, mande o vídeo para o agent e peça para ele montar na linha do tempo original.
   - Automático: se você tem o [capsule-cinema](https://github.com/JuneYaooo/capsule-cinema) instalado, diga "recria os planos de IA com o capsule-cinema" e o agent chama o modelo de vídeo, monta tudo sozinho e gera o comparativo. Chamar o modelo custa dinheiro, então ele faz antes uma rodada de teste grátis e só gera de verdade depois que você confirmar.
3. Por enquanto a geração automática ainda chama o modelo uma vez por plano. O relatório já traz prompts que geram vários planos de uma vez, o que sai mais barato, mas hoje isso só funciona pelo caminho manual.

## Código / animação de interface: escreva código

O relatório traz o texto, o layout e o ritmo da animação de cada trecho. Peça para o agent "escrever um projeto Remotion seguindo o relatório"; depois, para mudar o texto, é só mexer nos dados. A ferramenta ainda não gera esse projeto sozinha, quem escreve é o agent.

## Imagem estática com zoom/pan: gere localmente

Uma imagem mais a velocidade de zoom e deslocamento medida: o agent gera direto na sua máquina, sem chamar modelo nenhum.

## Som: três trilhas, cada uma do seu jeito

- Locução: o texto está no relatório; gere com TTS ou grave você mesmo.
- Trilha: procure num banco de músicas pelo BPM, tonalidade e estilo, ou gere no Suno.
- Efeitos sonoros: coloque seguindo a tabela de tempos.
