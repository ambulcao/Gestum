# Gestum

Mouse controlado por gestos da mão, pela câmera.

O que faz • Gestos • Requisitos • Rodar nesta máquina • Configuração • Uso • Operação • Testes

Python OpenCV MediaPipe GTK libei GNOME

O Gestum lê a câmera, acompanha a mão e transforma cada pose em movimento, clique, rolagem ou arraste. O cursor visível do GNOME recebe esses eventos pelo compositor, via Mutter e libei. A imagem da câmera fica na máquina.

## O que faz

| Recurso | Descrição |
| --- | --- |
| Prévia | Janela GTK 3. A câmera ocupa 1280×960 e os comandos ficam numa coluna à direita |
| Mão | MediaPipe Tasks localiza até duas mãos e desenha só a escolhida |
| Pessoa mais perto | O rosto maior é a PESSOA 1. A mão maior, quando é bem maior que a outra, é a que comanda |
| Cursor | O deslocamento da ponta do dedo move o ponteiro. Cada pixel da mão vale 8 pixels na tela |
| Cliques e rolagem | Clique esquerdo, direito e duplo, rolagem com zona morta e arraste com o botão segurado |
| Reserva | Se o cursor do Wayland não subir, o movimento cai no ponteiro do X11 |

## Gestos

Cada comando é um conjunto de dedos levantados. A mão aberta fica parada. O polegar só entra no arraste.

| Gesto | Ação |
| --- | --- |
| Mão aberta | Parado. Solta o arraste |
| Só o indicador | Move o cursor |
| Indicador e médio | Mira. O clique esquerdo sai uma vez, quando as pontas ficam a menos de 40 px. Afaste para armar de novo |
| Indicador, médio e anelar | Clique direito, uma vez |
| Médio, anelar e mínimo | Clique duplo, uma vez |
| Médio e anelar | Rolagem. Mão no alto sobe; mão embaixo desce. Entre 40% e 60% da altura, não rola |
| Indicador e polegar, os outros fechados | Arraste. A pinça começa abaixo de 50 px e se mantém até 90 px |

Há 300 ms entre um clique e o seguinte. No clique direito e no duplo, mantenha o mínimo na posição do gesto: se ele subir junto com os outros, a pose muda.

## Requisitos

| Item | Nesta máquina |
| --- | --- |
| Sistema | Bazzite ou Fedora com GNOME em Wayland |
| Python | 3, com OpenCV, MediaPipe, NumPy, Pillow, autopy, python-xlib e PyGObject (GTK 3) |
| Sistema | `libei`, `v4l2-ctl` e a fonte Lato |
| Câmera | Uma webcam colorida. A câmera virtual do OBS e o sensor cinza do notebook são ignorados |
| Modelos | `hand_landmarker.task` e `blaze_face_short_range.tflite` na pasta do projeto |
| Sessão | Cookie do X11 em `$HOME/.Xauthority`, para a reserva do ponteiro |

Os modelos desta pasta já estão no lugar. Numa cópia nova, baixe os oficiais do MediaPipe e deixe os arquivos com esses nomes:

```bash
curl -L -o hand_landmarker.task \
  https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task
curl -L -o blaze_face_short_range.tflite \
  https://storage.googleapis.com/mediapipe-models/face_detector/blaze_face_short_range/float16/1/blaze_face_short_range.tflite
```

## Rodar nesta máquina

```bash
cd /run/media/system/DadosBazzite/projetos/Virtual-Mouse-main
./iniciar.sh
```

O script entra na pasta do projeto, exporta `XAUTHORITY="$HOME/.Xauthority"` e executa `python Gestum.py`.

Na primeira linha útil do terminal deve aparecer a câmera escolhida, o tamanho da tela e `Gestum iniciado!`. A janela se chama Gestum. Feche com `q` ou Esc nessa janela.

Se o cookie do X11 mudar depois de reiniciar o computador, copie de novo o cookie da sessão do GNOME para `$HOME/.Xauthority` antes de abrir o programa. O script só aponta a variável para esse arquivo.

Luz de frente e fundo simples deixam a mão mais estável. Com duas pessoas no quadro, aproxime a mão de quem vai comandar: a mão maior tem prioridade.

## Configuração

Os valores ficam no início de `Gestum.py`.

| Constante | Função | Valor |
| --- | --- | --- |
| `wCam`, `hCam` | Resolução da captura | 640×480 |
| `preview_scale` | Ampliação da janela | 2 |
| `frameR`, `frameR_top` | Margem da área de detecção | 8 px. O quadro da câmera fica quase todo livre |
| `cursor_gain` | Pixels do cursor por pixel da mão | 8 |
| `click_cooldown` | Intervalo mínimo entre cliques | 0,3 s |
| `scroll_deadzone_min`, `scroll_deadzone_max` | Faixa em que a rolagem não anda | 40%–60% |
| `scroll_sensitivity` | Cliques por quadro no extremo da rolagem. O teto é 10 por quadro e 100 por segundo | 3 |

A confiança mínima da mão é 0,8. A do rosto é 0,5. As duas ficam em `HandTrackingModule.py`.

## Uso

1. Abra o Gestum com `./iniciar.sh` e confira se a sua mão aparece dentro da área magenta.
2. Deixe a mão aberta enquanto posiciona.
3. Levante só o indicador para mover o cursor.
4. Para o clique esquerdo, levante indicador e médio, mire e junte as pontas. O painel passa de Mirando para Clique esquerdo.
5. Use os outros gestos da tabela. O guia fica na coluna à direita da câmera, e a linha ativa fica marcada.
6. Pressione `q` na janela para encerrar. O programa solta o botão do arraste ao sair.

## Operação

O terminal registra cada ação com o horário, por exemplo `CLIQUE ESQUERDO` e `ARRASTE INICIADO`. A linha `Cursor do Wayland ativo.` confirma que o ponteiro do GNOME está recebendo o movimento.

Alterou o código? Feche com `q` e rode `./iniciar.sh` de novo. A janela que já está aberta continua com a versão anterior.

Se a câmera não abrir, outra instância pode estar segurando `/dev/video1`. Encerre esse processo e inicie outra vez. A mensagem `Nao foi possivel ler a camera` também aparece quando nenhum dispositivo colorido entrega quadro.

Um aviso `Pipe quebrado` da libei na subida pode ocorrer uma vez e o cursor seguir funcionando. Se aparecer `Cursor do Wayland indisponível`, o movimento fica só no ponteiro do X11.

A imagem da câmera não é enviada para fora. Os modelos de mão e de rosto rodam no processo local.

## Testes

O projeto não tinha testes. Há 93 em `tests/`. Eles simulam câmera, MediaPipe, janela e mouse, então nada foi exercitado com a webcam de verdade. 79 passam e 14 falham de propósito: marcam bugs já conhecidos, para a correção seguir o caderno em `doc/caderno-de-testes.md`.

Para rodar:

```bash
python3 -m pytest tests -q -rx
```
