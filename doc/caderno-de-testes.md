# Caderno de testes

Histórico do que foi testado e do que foi corrigido. Cada rodada recebe um número: Bug 001 é a primeira. O Bug 002 só nasce depois que o Bug 001 estiver corrigido e uma nova execução ainda encontrar falha.

As marcas `BUG-001` a `BUG-009` e `M-04` dentro de `tests/` são os itens desta primeira rodada. Elas não abrem uma rodada nova.

## Histórico

| Identificação | Data | O que foi testado | O que foi corrigido | Situação |
| --- | --- | --- | --- | --- |
| Bug 001 | 11 out 2026 | 93 testes em `tests/`, com câmera, MediaPipe, janela e mouse simulados. Nada com a webcam. 76 passaram e 17 falharam de propósito. A leitura do código ainda apontou o caminho fixo da fonte Lato, sem teste automático | 001.1: a rolagem usa `scroll_sensitivity`, com no máximo 10 cliques por quadro e 100 por segundo | Aberto |

Para rodar a suíte:

```bash
python3 -m pytest tests -q -rx
```

A suíte termina sem erro enquanto os 14 que restam continuarem falhando pelo motivo registrado. Quando a correção fizer o teste passar, o `strict=True` transforma essa passagem em erro. Retire a marca `xfail` desse teste e atualize a situação do item. Os 79 que já passam devem continuar passando.

## Bug 001

Primeira identificação, feita pelo agente de QA sobre a suíte simulada. Siga a ordem da tabela.

| Item | Severidade | Situação | O que o teste exige | O que o código faz hoje | Testes |
| --- | --- | --- | --- | --- | --- |
| 001.1 | Alta | Fechado | No máximo 10 cliques de rodinha por quadro e 100 em um segundo. `scroll_sensitivity` altera essa velocidade | No extremo, `scroll_sensitivity` cliques por quadro (3 com o valor atual), nunca acima de 10, e no máximo 100 na última janela de um segundo | `test_rolagem_no_topo_nao_passa_de_10_cliques_por_quadro`, `test_um_segundo_de_rolagem_maxima_fica_abaixo_de_100_cliques`, `test_scroll_sensitivity_altera_a_velocidade` |
| 001.2 | Alta | Aberto | Ao sair do arraste para outro gesto, soltar o botão esquerdo antes de mover, clicar ou rolar | O botão esquerdo continua preso | `test_arraste_e_solto_ao_passar_para_outro_gesto` (mover, esquerdo, direito, duplo, rolagem) |
| 001.3 | Média | Aberto | A troca de pose não dispara o gesto do quadro intermediário | Indicador e médio juntos, no caminho para o clique direito, geram clique esquerdo. O clique duplo aparece no caminho da mão aberta para a rolagem | `test_passar_de_mover_para_clique_direito_nao_gera_clique_esquerdo`, `test_passar_de_mao_aberta_para_rolagem_nao_gera_clique_duplo` |
| 001.4 | Média | Aberto | A janela cabe em 1920×1080 | A prévia fica em 2120×960 e não pode ser redimensionada | `test_janela_cabe_numa_tela_full_hd` |
| 001.5 | Média | Aberto | Sem `libei.so.1`, o movimento usa a reserva do X11 | A ausência da biblioteca derruba o programa | `test_sem_libei_o_programa_usa_a_reserva_x11` |
| 001.6 | Média | Aberto | Com a libei conectada e o dispositivo perdido, o clique duplo cai no autopy | O clique duplo olha `ponteiro.ok` e não usa a reserva | `test_clique_duplo_cai_no_autopy_quando_libei_perde_o_dispositivo` |
| 001.7 | Média | Aberto | Uma falha isolada de leitura segue para o quadro seguinte | O primeiro quadro que falha encerra o programa | `test_falha_isolada_de_leitura_nao_encerra_o_programa` |
| 001.8 | Média | Aberto | Dispositivo pausado para de emular. Dispositivo removido é descartado | O evento de pausa marca `emulando=True`. O evento de remoção é ignorado. Visto só na simulação | `test_libei_paused_para_de_emular`, `test_libei_removed_descarta_o_dispositivo` |
| 001.9 | Baixa | Aberto | `/dev/video11` a `/dev/video19` não tomam o lugar de `/dev/video1` | A comparação pelo sufixo `video1` também aceita esses dispositivos. O teste cobre o `video11` | `test_camera_sources_prioridade_nao_confunde_video11` |
| 001.10 | Baixa | Aberto | A fonte do painel é encontrada também em Debian e Ubuntu | O caminho está fixo em `/usr/share/fonts/lato-fonts/Lato-Regular.ttf` | Sem teste automático. Conferir ao desenhar o painel |

### Como fechar um item do Bug 001

1. Leia o teste citado e o trecho de `Gestum.py` que ele exercita. O item 001.10 não tem teste: confira a fonte no código.
2. Ajuste o programa para o resultado da coluna "O que o teste exige".
3. Rode `python3 -m pytest tests -q -rx`.
4. Se o teste do item passou e os outros 79 continuam passando, apague o `@pytest.mark.xfail` desse teste.
5. Rode a suíte outra vez. Ela precisa terminar sem `XPASS`.
6. Marque a situação do item como Fechado.

Quando todos os itens estiverem Fechado, atualize a linha do Bug 001 no histórico: escreva o que foi corrigido e mude a situação para Corrigido.

## Bug 002

Ainda não existe. Abra esta rodada só depois do Bug 001 corrigido, se uma nova execução ainda mostrar falha.

1. Rode `python3 -m pytest tests -q -rx`.
2. Se fizer sentido para o que mudou, rode também `./iniciar.sh` e confira a mão na câmera.
3. Havendo falha nova, copie a tabela do Bug 001 para uma seção Bug 002, numere os itens como 002.1, 002.2, e acrescente uma linha no histórico com o que foi testado.
4. Sem falha nova, o histórico permanece no Bug 001 corrigido.
