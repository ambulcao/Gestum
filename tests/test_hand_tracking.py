"""Testes da lógica pura do HandTrackingModule (sem rodar os modelos)."""

import types

import numpy as np
import pytest

htm = pytest.importorskip("HandTrackingModule")


def detector_com(pontos):
    """handDetector sem __init__ (não carrega o modelo) e com lmList pronto."""
    d = htm.handDetector.__new__(htm.handDetector)
    d.tipIds = [4, 8, 12, 16, 20]
    d.lmList = [[i, x, y] for i, (x, y) in enumerate(pontos)]
    return d


def mao(polegar_aberto, dedos_levantados):
    """Mão em pé, palma para a câmera. dedos_levantados: 4 bools (indicador..mínimo)."""
    pts = [(320, 400)] + [(0, 0)] * 20  # 0 = pulso
    # Polegar: 1..4
    if polegar_aberto:
        pts[1:5] = [(290, 380), (270, 360), (255, 345), (235, 325)]
    else:
        pts[1:5] = [(300, 380), (295, 360), (300, 345), (305, 350)]
    for n, levantado in enumerate(dedos_levantados):
        x = 290 + n * 20
        base = 4 + n * 4  # 5, 9, 13, 17 = MCP
        if levantado:
            ys = [320, 280, 250, 220]
        else:
            ys = [320, 300, 315, 325]  # ponta abaixo do PIP
        for k in range(4):
            pts[base + 1 + k] = (x, ys[k])
    return pts


@pytest.mark.parametrize("polegar,dedos,esperado", [
    (True, [1, 1, 1, 1], [1, 1, 1, 1, 1]),
    (False, [0, 0, 0, 0], [0, 0, 0, 0, 0]),
    (False, [1, 0, 0, 0], [0, 1, 0, 0, 0]),
    (False, [0, 1, 1, 0], [0, 0, 1, 1, 0]),
    (True, [1, 0, 0, 0], [1, 1, 0, 0, 0]),
])
def test_fingers_up(polegar, dedos, esperado):
    assert detector_com(mao(polegar, dedos)).fingersUp() == esperado


def test_fingers_up_com_menos_de_21_pontos_devolve_lista_vazia():
    d = detector_com([(0, 0)] * 10)
    assert d.fingersUp() == []


def test_find_position_converte_coordenadas_normalizadas():
    d = htm.handDetector.__new__(htm.handDetector)
    d.tipIds = [4, 8, 12, 16, 20]
    d.landmarks = [types.SimpleNamespace(x=i / 20, y=0.5) for i in range(21)]
    img = np.zeros((480, 640, 3), np.uint8)
    lm, bbox = d.findPosition(img, draw=False)
    assert lm[0] == [0, 0, 240] and lm[20] == [20, 640, 240]
    assert bbox == (0, 240, 640, 240)


def test_find_position_sem_mao():
    d = htm.handDetector.__new__(htm.handDetector)
    d.tipIds = [4, 8, 12, 16, 20]
    d.landmarks = []
    assert d.findPosition(np.zeros((10, 10, 3), np.uint8), draw=False) == ([], [])


def test_listar_maos_calcula_centro_e_caixa():
    d = htm.handDetector.__new__(htm.handDetector)
    d.todas = [[types.SimpleNamespace(x=0.25, y=0.25), types.SimpleNamespace(x=0.75, y=0.75)]]
    maos = d.listar_maos(np.zeros((400, 800, 3), np.uint8))
    assert maos[0]["bbox"] == (200, 100, 600, 300)
    assert (maos[0]["cx"], maos[0]["cy"]) == (400, 200)


def test_find_distance():
    d = detector_com([(0, 0)] * 4 + [(3, 4)] + [(0, 0)] * 3 + [(0, 0)] + [(0, 0)] * 12)
    comprimento, info = d.findDistance(4, 8, draw=False)
    assert comprimento == 5 and info[:4] == [3, 4, 0, 0]
