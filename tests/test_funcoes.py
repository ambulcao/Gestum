"""Testes das funções auxiliares do Gestum.py.

O módulo é carregado pelo harness com um roteiro vazio: o laço termina no
primeiro quadro e as funções ficam disponíveis no namespace.
"""

import subprocess

import numpy as np
import pytest
from PIL import ImageFont

from conftest import executar_gestum

V4L2_LIST = """OBS Virtual Camera (platform:v4l2loopback-000):
\t/dev/video0

Web Camera: Web Camera (usb-0000:00:14.0-3.1):
\t/dev/video1
\t/dev/video2
\t/dev/media0

Integrated Camera: Integrated C (usb-0000:00:14.0-9):
\t/dev/video3
\t/dev/video4
\t/dev/video5
\t/dev/video6
\t/dev/media1
\t/dev/media2
"""

XRANDR = """Screen 0: minimum 16 x 16, current 4480 x 1800, maximum 32767 x 32767
DP-1 connected 1920x1080+2560+360 (normal left inverted right x axis y axis) 520mm x 290mm
DP-4 connected primary 2560x1440+0+0 (normal left inverted right x axis y axis) 600mm x 330mm
HDMI-1 disconnected (normal left inverted right x axis y axis)
"""


@pytest.fixture
def ns(monkeypatch):
    namespace, reg, _ = executar_gestum([], monkeypatch)
    namespace["_reg"] = reg
    return namespace


# ---------------------------------------------------------------- distância

def test_calculate_distance_triangulo_3_4_5(ns):
    assert ns["calculate_distance"]((0, 0), (3, 4)) == 5


def test_calculate_distance_mesmo_ponto(ns):
    assert ns["calculate_distance"]((7, 7), (7, 7)) == 0


# ---------------------------------------------------------------- rolagem

@pytest.mark.parametrize("pos", [40, 45.5, 50, 60])
def test_zona_morta_inclui_os_limites(ns, pos):
    assert ns["perform_smart_scroll"](pos) == "deadzone"


@pytest.mark.parametrize("pos,direcao,cliques", [
    (39.99, "up", 1), (35, "up", 1), (0, "up", 3),
    (60.01, "down", -1), (65, "down", -1), (100, "down", -3),
])
def test_velocidade_da_rolagem(ns, monkeypatch, pos, direcao, cliques):
    chamadas = []
    monkeypatch.setitem(ns, "scroll_wheel", chamadas.append)
    assert ns["perform_smart_scroll"](pos) == direcao
    assert chamadas == [cliques]


def test_erro_na_rolagem_e_capturado(ns, monkeypatch):
    def quebra(_):
        raise RuntimeError("X11 sem cookie")
    monkeypatch.setitem(ns, "scroll_wheel", quebra)
    assert ns["perform_smart_scroll"](0) == "none"


def test_scroll_wheel_zero_nao_faz_nada(ns):
    ns["scroll_wheel"](0)
    assert ns["_reg"].de_tipo("fake_input") == []


def test_scroll_wheel_negativo_usa_botao_5(ns):
    ns["scroll_wheel"](-3)
    assert ns["_reg"].de_tipo("fake_input") == [("press", 5), ("release", 5)] * 3


def test_mapeamento_da_altura_para_porcentagem(ns):
    """O trecho da linha ~1003: np.interp com (frameR_top, hCam - frameR)."""
    interp = lambda y: np.interp(y, (ns["frameR_top"], ns["hCam"] - ns["frameR"]), (0, 100))
    assert interp(0) == 0 and interp(8) == 0
    assert interp(240) == pytest.approx(50)
    assert interp(472) == 100 and interp(480) == 100
    # Zona morta de 40%-60% corresponde a y entre 193,6 e 286,4 px.
    assert interp(193.6) == pytest.approx(40) and interp(286.4) == pytest.approx(60)


def test_scroll_sensitivity_altera_a_velocidade(ns, monkeypatch):
    chamadas = []
    monkeypatch.setitem(ns, "scroll_wheel", chamadas.append)
    ns["perform_smart_scroll"](0)
    monkeypatch.setitem(ns, "scroll_sensitivity", 1)
    ns["perform_smart_scroll"](0)
    assert chamadas[0] != chamadas[1]


# ---------------------------------------------------------------- câmera

def test_frame_has_image(ns):
    f = ns["_frame_has_image"]
    assert not f(None)
    assert not f(np.zeros((0, 0, 3), np.uint8))
    assert not f(np.full((4, 4, 3), 12, np.uint8))
    assert f(np.full((4, 4, 3), 13, np.uint8))


def test_camera_sources_ignora_obs_e_sensor_cinza(ns, monkeypatch):
    def check_output(cmd, **kw):
        if cmd[:2] == ["v4l2-ctl", "--list-devices"]:
            return V4L2_LIST
        return "Pixel Format      : 'YUYV'"
    monkeypatch.setattr(subprocess, "check_output", check_output)
    assert ns["_camera_sources"]() == ["/dev/video1", "/dev/video3"]


def test_camera_sources_sem_v4l2_tenta_indices_0_a_9(ns):
    # O harness faz o subprocess falhar com OSError.
    assert ns["_camera_sources"]() == list(range(10))


@pytest.mark.xfail(strict=True, reason="BUG-008: endswith('video1') também prioriza /dev/video11")
def test_camera_sources_prioridade_nao_confunde_video11(ns, monkeypatch):
    lista = "Cam A (usb-1):\n\t/dev/video11\n\nCam B (usb-2):\n\t/dev/video3\n"
    monkeypatch.setattr(subprocess, "check_output",
                        lambda cmd, **kw: lista if "--list-devices" in cmd else "YUYV")
    assert ns["_camera_sources"]() == ["/dev/video3", "/dev/video11"]


# ---------------------------------------------------------------- escolha da mão

def _mao(x1, y1, x2, y2):
    return {"bbox": (x1, y1, x2, y2), "cx": (x1 + x2) / 2, "cy": (y1 + y2) / 2, "landmarks": None}


def test_area_mao_nunca_e_zero(ns):
    assert ns["area_mao"](_mao(5, 5, 5, 5)) == 1


def test_escolher_mao_sem_maos(ns):
    assert ns["escolher_mao"]([], [], None, 0) == (None, None)


def test_escolher_mao_prefere_a_maior_quando_bem_maior(ns):
    grande, pequena = _mao(0, 0, 100, 100), _mao(300, 300, 350, 350)
    rosto = {"cx": 325, "cy": 325}
    escolhida, _ = ns["escolher_mao"]([rosto], [pequena, grande], None, 0)
    assert escolhida is grande


def test_escolher_mao_de_tamanho_parecido_usa_a_mais_perto_do_rosto(ns):
    a, b = _mao(0, 0, 100, 100), _mao(300, 300, 395, 395)
    rosto = {"cx": 340, "cy": 340}
    escolhida, prioritaria = ns["escolher_mao"]([rosto], [a, b], None, 0)
    assert escolhida is b and prioritaria is rosto


# ---------------------------------------------------------------- monitores

def test_list_monitors_le_xrandr_e_marca_a_principal(ns, monkeypatch):
    monkeypatch.setattr(subprocess, "check_output", lambda *a, **k: XRANDR)
    monkeypatch.setitem(ns, "_monitor_cache", [])
    mons = ns["list_monitors"]()
    assert mons == [(2560, 360, 1920, 1080), (0, 0, 2560, 1440)]
    assert ns["_primary_monitor"] == (0, 0, 2560, 1440)


def test_monitor_at_e_monitor_label(ns):
    mons = [(2560, 360, 1920, 1080), (0, 0, 2560, 1440)]
    assert ns["monitor_at"](3000, 500, mons) == mons[0]
    assert ns["monitor_at"](-50, 10, mons) == mons[1]  # fora: o mais próximo
    assert ns["monitor_label"](mons[1], mons) == "tela da esquerda"
    assert ns["monitor_label"](mons[0], mons) == "tela da direita"
    assert ns["monitor_label"](mons[0], mons[:1]) == "esta tela"


# ---------------------------------------------------------------- painel

def test_usar_gesto_avisa_so_na_mudanca(ns):
    assert ns["usar_gesto"]("mover") is True
    assert ns["usar_gesto"]("mover") is False
    assert ns["usar_gesto"]("rolagem") is True


def test_painel_tem_altura_da_camera_e_largura_do_painel(ns):
    painel = ns["desenhar_painel"](30)
    assert painel.shape == (480, 420, 3)


@pytest.mark.parametrize("gesto", ["", "parado", "mover", "esquerdo", "direito", "duplo", "rolagem", "arraste"])
def test_painel_desenha_todos_os_estados(ns, monkeypatch, gesto):
    monkeypatch.setitem(ns, "gesto_atual", gesto)
    tela = ns["montar_tela"](np.zeros((480, 640, 3), np.uint8), 29.7)
    assert tela.shape == (480, 1060, 3)


@pytest.mark.parametrize("pos", [0, 50, 100])
def test_barra_de_rolagem_nos_extremos(ns, pos):
    img = np.zeros((480, 420, 3), np.uint8)
    ns["draw_scroll_bar"](img, pos, 394, 40, 392)
    assert img[40:432, 394:409].any()


def test_textos_do_painel_nao_invadem_a_barra(ns):
    fonte = ImageFont.truetype("/usr/share/fonts/lato-fonts/Lato-Regular.ttf", 13)
    limite = ns["painel_largura"] - 26 - 10
    for _, texto, *_ in ns["_gestos_do_painel"]():
        largura = fonte.getbbox(texto)[2]
        assert 46 + largura <= limite, f"{texto!r} termina em {46 + largura}px (limite {limite})"


def test_lista_do_painel_cabe_acima_da_linha_de_estado(ns):
    linhas = ns["_gestos_do_painel"]()
    fim = 36 + 34 * len(linhas) + 31  # 31 px das duas linhas extras da rolagem
    assert fim <= ns["hCam"] - 46


# ---------------------------------------------------------------- libei (PonteiroWayland)
# Números dos eventos conferidos com ei_event_type_to_string() da libei 1.6.0:
# 5=DEVICE_ADDED, 6=DEVICE_REMOVED, 7=DEVICE_PAUSED, 8=DEVICE_RESUMED.

from unittest.mock import MagicMock  # noqa: E402

DISPOSITIVO = 0x1234


def _ponteiro(ns, tipo_evento):
    cls = ns["PonteiroWayland"]
    p = cls.__new__(cls)
    p.ok, p.emulando, p.ei, p.abs, p._seq = True, True, 0x1, None, 1
    p.rel = DISPOSITIVO
    lib = MagicMock()
    lib.ei_event_get_type.return_value = tipo_evento
    lib.ei_event_get_device.return_value = DISPOSITIVO
    lib.ei_device_has_capability.side_effect = lambda dev, cap: cap == 1
    lib.ei_device_ref.side_effect = lambda dev: dev
    lib.ei_get_event.return_value = None  # fila de eventos vazia
    p.lib = lib
    return p


def test_libei_resumed_comeca_a_emular(ns):
    p = _ponteiro(ns, 8)
    p.emulando = False
    p._tratar(0xE)
    assert p.emulando is True
    p.lib.ei_device_start_emulating.assert_called_once_with(DISPOSITIVO, 1)


@pytest.mark.xfail(strict=True, reason="BUG-009: DEVICE_PAUSED (7) marca emulando=True")
def test_libei_paused_para_de_emular(ns):
    p = _ponteiro(ns, 7)
    p._tratar(0xE)
    assert p.emulando is False


@pytest.mark.xfail(strict=True, reason="BUG-009: DEVICE_REMOVED (6) é ignorado e o dispositivo fica em uso")
def test_libei_removed_descarta_o_dispositivo(ns):
    p = _ponteiro(ns, 6)
    p._tratar(0xE)
    assert p.rel is None


def test_libei_rolar_converte_cliques_em_120_unidades(ns):
    p = _ponteiro(ns, 0)
    assert p.rolar(2) is True
    p.lib.ei_device_scroll_discrete.assert_called_once_with(DISPOSITIVO, 0, -240)


def test_libei_rolar_zero_nao_envia(ns):
    p = _ponteiro(ns, 0)
    assert p.rolar(0) is False
    p.lib.ei_device_scroll_discrete.assert_not_called()
