"""Testes do laço principal do Gestum.py com um roteiro de quadros simulado.

Sem libei (o D-Bus falha no harness), todo clique e arraste cai no autopy e a
rolagem cai no XTest. O harness registra essas chamadas em ``reg``.
"""

import pytest

from conftest import (
    DIREITO, DUPLO, ESQUERDO, FALHA, MOVER, NENHUM, PARADO, PINCA, ROLAGEM, quadro,
)

PERTO = dict(polegar=(325, 208), indicador=(320, 200))  # pinça: ~9 px


def pinca(**kw):
    base = dict(PERTO)
    base.update(kw)
    return quadro(PINCA, **base)


# --------------------------------------------------------------------------
# Movimento
# --------------------------------------------------------------------------

def test_mover_desloca_cursor_com_ganho_8(gestum):
    _, reg, _ = gestum([
        quadro(MOVER, indicador=(320, 200)),
        quadro(MOVER, indicador=(330, 195)),
    ])
    assert reg.de_tipo("move") == [(960 + 80, 540 - 40)]


def test_primeiro_quadro_de_movimento_nao_salta_o_cursor(gestum):
    _, reg, _ = gestum([quadro(MOVER, indicador=(600, 50))])
    assert reg.de_tipo("move") == []


def test_mao_aberta_nao_move_nem_clica(gestum):
    _, reg, _ = gestum([quadro(PARADO, indicador=(100 + i * 10, 100)) for i in range(10)])
    assert reg.eventos == []


def test_cursor_fica_dentro_da_tela(gestum):
    roteiro = [quadro(MOVER, indicador=(320, 240))]
    roteiro += [quadro(MOVER, indicador=(320 + 100 * i, 240)) for i in range(1, 4)]
    _, reg, _ = gestum(roteiro)
    x, y = reg.de_tipo("move")[-1]
    assert 0 <= x <= 1919 and 0 <= y <= 1079


# --------------------------------------------------------------------------
# Clique esquerdo
# --------------------------------------------------------------------------

def test_clique_esquerdo_sai_uma_vez_ao_juntar_as_pontas(gestum):
    separado = quadro(ESQUERDO, indicador=(300, 200), medio=(360, 200))
    junto = quadro(ESQUERDO, indicador=(320, 200), medio=(340, 200))
    _, reg, _ = gestum([separado] * 3 + [junto] * 10)
    assert reg.cliques("LEFT") == ["LEFT"]


def test_clique_esquerdo_rearma_ao_afastar_depois_do_cooldown(gestum):
    separado = quadro(ESQUERDO, indicador=(300, 200), medio=(360, 200))
    junto = quadro(ESQUERDO, indicador=(320, 200), medio=(340, 200))
    roteiro = [separado, junto] + [separado] * 12 + [junto]  # ~0,4 s depois
    _, reg, _ = gestum(roteiro)
    assert len(reg.cliques("LEFT")) == 2


def test_clique_esquerdo_respeita_cooldown_de_300ms(gestum):
    separado = quadro(ESQUERDO, indicador=(300, 200), medio=(360, 200))
    junto = quadro(ESQUERDO, indicador=(320, 200), medio=(340, 200))
    _, reg, _ = gestum([separado, junto, separado, junto])  # 66 ms entre as junções
    assert len(reg.cliques("LEFT")) == 1


# --------------------------------------------------------------------------
# Clique direito e duplo
# --------------------------------------------------------------------------

def test_clique_direito_sai_uma_vez_por_gesto(gestum):
    _, reg, _ = gestum([quadro(DIREITO)] * 30)
    assert reg.cliques("RIGHT") == ["RIGHT"]


def test_clique_direito_repete_apos_desfazer_e_refazer_o_gesto(gestum):
    _, reg, _ = gestum([quadro(DIREITO)] * 3 + [quadro(PARADO)] * 12 + [quadro(DIREITO)] * 3)
    assert len(reg.cliques("RIGHT")) == 2


def test_clique_duplo_no_fallback_autopy_gera_dois_cliques(gestum):
    _, reg, _ = gestum([quadro(DUPLO)] * 20)
    assert reg.cliques("LEFT") == ["LEFT", "LEFT"]


def _libei_ok_sem_dispositivo(ns):
    """libei conectou (ok=True), mas o dispositivo foi pausado/perdido."""
    p = ns["ponteiro"]
    p.ok = True
    p.emulando = False
    p.rel = None
    p.abs = None


def test_clique_esquerdo_cai_no_autopy_quando_libei_perde_o_dispositivo(gestum):
    """Controle positivo: o clique esquerdo testa o retorno de ponteiro.clique()."""
    separado = quadro(ESQUERDO, indicador=(300, 200), medio=(360, 200))
    junto = quadro(ESQUERDO, indicador=(320, 200), medio=(340, 200))
    _, reg, _ = gestum([separado, junto], gancho=_libei_ok_sem_dispositivo)
    assert reg.cliques("LEFT") == ["LEFT"]


@pytest.mark.xfail(strict=True, reason="BUG-005: clique duplo testa ponteiro.ok e não cai no autopy")
def test_clique_duplo_cai_no_autopy_quando_libei_perde_o_dispositivo(gestum):
    _, reg, _ = gestum([quadro(DUPLO)] * 5, gancho=_libei_ok_sem_dispositivo)
    assert reg.cliques("LEFT") == ["LEFT", "LEFT"]


# --------------------------------------------------------------------------
# Rolagem
# --------------------------------------------------------------------------

def _rolagem_em(y):
    return quadro(ROLAGEM, medio=(340, y), anelar=(360, y))


def test_rolagem_na_zona_morta_nao_rola(gestum):
    _, reg, _ = gestum([_rolagem_em(240)] * 10)
    assert reg.de_tipo("fake_input") == []


def test_rolagem_mao_no_alto_rola_para_cima(gestum):
    _, reg, _ = gestum([_rolagem_em(150)])
    assert reg.rodinha(4) and not reg.rodinha(5)


def test_rolagem_mao_embaixo_rola_para_baixo(gestum):
    _, reg, _ = gestum([_rolagem_em(330)])
    assert reg.rodinha(5) and not reg.rodinha(4)


def test_rolagem_no_topo_nao_passa_de_10_cliques_por_quadro(gestum):
    _, reg, _ = gestum([_rolagem_em(8)])
    assert len(reg.rodinha(4)) <= 10, f"{len(reg.rodinha(4))} cliques num único quadro"


def test_um_segundo_de_rolagem_maxima_fica_abaixo_de_100_cliques(gestum):
    _, reg, _ = gestum([_rolagem_em(8)] * 30)
    assert len(reg.rodinha(4)) <= 100, f"{len(reg.rodinha(4))} cliques em 1 s"


def test_rolagem_logo_fora_da_zona_morta_ja_gera_varios_cliques(gestum):
    """Logo abaixo da zona morta a rolagem anda um clique por quadro."""
    _, reg, _ = gestum([_rolagem_em(300)])  # 62,9%
    assert len(reg.rodinha(5)) == 1


# --------------------------------------------------------------------------
# Arraste
# --------------------------------------------------------------------------

def test_pinca_inicia_arraste_e_mao_aberta_solta(gestum):
    _, reg, _ = gestum([pinca()] * 5 + [quadro(PARADO)])
    assert reg.de_tipo("toggle") == [True, False]


def test_arraste_move_o_cursor_com_o_botao_preso(gestum):
    _, reg, _ = gestum([pinca(), pinca(indicador=(330, 200), polegar=(335, 208)), quadro(PARADO)])
    tipos = [t for t, _ in reg.eventos]
    assert tipos == ["toggle", "move", "toggle"]


def test_arraste_tolera_perda_curta_da_mao(gestum):
    _, reg, _ = gestum([pinca()] * 3 + [None] * 3 + [pinca()] * 3 + [quadro(PARADO)])
    assert reg.de_tipo("toggle") == [True, False]


def test_arraste_solta_quando_a_mao_some_por_mais_que_a_tolerancia(gestum):
    _, reg, _ = gestum([pinca()] * 3 + [None] * 15)
    assert reg.de_tipo("toggle") == [True, False]


def test_arraste_solta_quando_a_mao_salta_mais_de_180px(gestum):
    _, reg, _ = gestum([pinca()] * 3 + [quadro(NENHUM, centro=(600, 400))])
    assert reg.de_tipo("toggle") == [True, False]


def test_programa_solta_o_arraste_ao_encerrar(gestum):
    _, reg, cam = gestum([pinca()] * 3)
    assert reg.de_tipo("toggle") == [True, False]
    assert cam.liberada


@pytest.mark.parametrize("dedos", [MOVER, ESQUERDO, DIREITO, DUPLO, ROLAGEM],
                         ids=["mover", "esquerdo", "direito", "duplo", "rolagem"])
def test_arraste_e_solto_ao_passar_para_outro_gesto(gestum, dedos):
    # 1 s no outro gesto, com a mão andando (gera movimento) e o médio/anelar
    # no alto (fora da zona morta da rolagem).
    roteiro = [pinca()] * 3 + [
        quadro(dedos, indicador=(300 + i, 200), medio=(360 + i, 100), anelar=(380 + i, 100))
        for i in range(30)
    ]
    _, reg, _ = gestum(roteiro)
    # O toggle(False) final vem do encerramento do programa; o esperado é
    # soltar durante o outro gesto, antes de qualquer outro evento de mouse.
    toggles = [i for i, (t, _) in enumerate(reg.eventos) if t == "toggle"]
    outros = [i for i, (t, _) in enumerate(reg.eventos) if t != "toggle"]
    assert len(toggles) == 2
    assert not outros or toggles[1] < outros[0], (
        f"eventos com o botão preso: {[reg.eventos[i] for i in outros][:4]}"
    )


# --------------------------------------------------------------------------
# Transições entre gestos
# --------------------------------------------------------------------------

@pytest.mark.xfail(strict=True, reason="BUG-003: pose intermediária dispara clique esquerdo")
def test_passar_de_mover_para_clique_direito_nao_gera_clique_esquerdo(gestum):
    # Ao levantar médio e anelar, um quadro intermediário mostra só indicador+médio,
    # com as pontas lado a lado (< 40 px).
    intermediario = quadro(ESQUERDO, indicador=(320, 200), medio=(345, 200))
    _, reg, _ = gestum([quadro(MOVER)] * 3 + [intermediario] + [quadro(DIREITO)] * 5)
    assert reg.cliques("LEFT") == []


@pytest.mark.xfail(strict=True, reason="BUG-003: pose intermediária dispara clique duplo")
def test_passar_de_mao_aberta_para_rolagem_nao_gera_clique_duplo(gestum):
    # Da mão aberta para a rolagem, o indicador pode fechar antes do mínimo.
    _, reg, _ = gestum([quadro(PARADO)] * 3 + [quadro(DUPLO)] + [_rolagem_em(240)] * 5)
    assert reg.cliques("LEFT") == []


# --------------------------------------------------------------------------
# Câmera
# --------------------------------------------------------------------------

def test_falha_de_leitura_encerra_e_libera_a_camera(gestum):
    _, reg, cam = gestum([FALHA])
    assert cam.liberada


@pytest.mark.xfail(strict=True, reason="BUG-006: uma falha de leitura isolada encerra o programa")
def test_falha_isolada_de_leitura_nao_encerra_o_programa(gestum):
    _, reg, cam = gestum([quadro(MOVER), FALHA, quadro(MOVER), quadro(MOVER, indicador=(330, 200))])
    assert cam.lidos == 5  # leu todos os quadros do roteiro e o fim


# --------------------------------------------------------------------------
# Janela
# --------------------------------------------------------------------------

def test_janela_mostra_camera_e_painel_em_dobro(gestum):
    _, reg, _ = gestum([quadro(MOVER)])
    assert reg.pixbufs[0] == ((640 + 420) * 2, 480 * 2)


@pytest.mark.xfail(strict=True, reason="BUG-004: janela de 2120 px não cabe numa tela Full HD")
def test_janela_cabe_numa_tela_full_hd(gestum):
    _, reg, _ = gestum([quadro(MOVER)])
    largura, altura = reg.pixbufs[0]
    assert largura <= 1920 and altura <= 1080


# --------------------------------------------------------------------------
# Dependências do sistema
# --------------------------------------------------------------------------

@pytest.mark.xfail(strict=True, raises=OSError,
                   reason="BUG-007: sem libei.so.1 o programa quebra em vez de usar o X11")
def test_sem_libei_o_programa_usa_a_reserva_x11(gestum):
    _, reg, _ = gestum([quadro(MOVER), quadro(MOVER, indicador=(330, 200))], libei_ausente=True)
    assert reg.de_tipo("move")
