"""Harness de testes do Gestum.

O Gestum.py é um script: abre a câmera, a janela GTK e o cursor da libei no
nível do módulo e entra direto no laço principal. Para testar sem webcam, sem
compositor e sem mexer no mouse real, este harness executa o arquivo original
(sem alterá-lo) com dublês para câmera, MediaPipe, GTK, libei, autopy e Xlib.

O OpenCV, o NumPy e o Pillow são os reais.

Uso:
    resultado = executar_gestum([quadro(...), quadro(...), None, ...])

Cada item da lista é um quadro da câmera. ``None`` significa "nenhuma mão
detectada"; ``FALHA`` significa que ``cap.read()`` falhou. Quando a lista
acaba, a câmera devolve falha e o laço termina.
"""

import ctypes
import os
import subprocess
import sys
import time
import types
from pathlib import Path
from unittest.mock import MagicMock

import cv2
import numpy as np
import pytest

RAIZ = Path(__file__).resolve().parent.parent
GESTUM = RAIZ / "Gestum.py"
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))  # para importar o HandTrackingModule real

FALHA = object()
DT = 1 / 30  # 30 quadros por segundo

# Índices de dedos em fingersUp(): polegar, indicador, médio, anelar, mínimo
PARADO = [1, 1, 1, 1, 1]
MOVER = [0, 1, 0, 0, 0]
ESQUERDO = [0, 1, 1, 0, 0]
DIREITO = [0, 1, 1, 1, 0]
DUPLO = [0, 0, 1, 1, 1]
ROLAGEM = [0, 0, 1, 1, 0]
PINCA = [1, 1, 0, 0, 0]
NENHUM = [0, 0, 0, 0, 0]


def quadro(dedos, polegar=(300, 300), indicador=(320, 200), medio=(360, 200),
           anelar=(380, 210), minimo=(400, 230), centro=None):
    """Monta um quadro com a mão, os dedos levantados e as pontas dos dedos."""
    pontos = {i: (320, 300) for i in range(21)}
    pontos.update({4: polegar, 8: indicador, 12: medio, 16: anelar, 20: minimo})
    lm = [[i, int(x), int(y)] for i, (x, y) in sorted(pontos.items())]
    xs = [p[1] for p in lm]
    ys = [p[2] for p in lm]
    if centro is None:
        centro = (sum(xs) / len(xs), sum(ys) / len(ys))
    return {
        "dedos": list(dedos),
        "lm": lm,
        "cx": centro[0],
        "cy": centro[1],
        "bbox": (min(xs), min(ys), max(xs), max(ys)),
    }


class Relogio:
    def __init__(self, inicio=1000.0):
        self.t = inicio

    def time(self):
        return self.t

    def avancar(self, dt=DT):
        self.t += dt


class Registro:
    """Tudo que o programa fez no "mundo de fora"."""

    def __init__(self):
        self.eventos = []  # sequência ordenada (tipo, dados)
        self.mouse_pos = [960.0, 540.0]
        self.botao_esquerdo_preso = False
        self.pixbufs = []  # (largura, altura) de cada quadro mostrado
        self.atexit = []
        self.quadro_atual = -1
        self.quadros_no_clique = []

    def de_tipo(self, tipo):
        return [dados for t, dados in self.eventos if t == tipo]

    def cliques(self, botao):
        return [d for d in self.de_tipo("click") if d == botao]

    def rodinha(self, botao):
        return [b for (ev, b) in self.de_tipo("fake_input") if ev == "press" and b == botao]


def _fake_autopy(reg):
    autopy = types.ModuleType("autopy")
    mouse = types.SimpleNamespace()
    mouse.Button = types.SimpleNamespace(LEFT="LEFT", RIGHT="RIGHT")

    def move(x, y):
        reg.mouse_pos = [x, y]
        reg.eventos.append(("move", (x, y)))

    def location():
        return tuple(reg.mouse_pos)

    def toggle(down=True, button=None):
        reg.botao_esquerdo_preso = bool(down)
        reg.eventos.append(("toggle", bool(down)))

    def click(button=None):
        reg.eventos.append(("click", button))
        reg.quadros_no_clique.append((reg.quadro_atual, button, reg.botao_esquerdo_preso))

    mouse.move = move
    mouse.location = location
    mouse.toggle = toggle
    mouse.click = click
    autopy.mouse = mouse
    autopy.screen = types.SimpleNamespace(size=lambda: (1920.0, 1080.0))
    return autopy


def _fake_xlib(reg):
    xlib = types.ModuleType("Xlib")
    x = types.ModuleType("Xlib.X")
    x.ButtonPress = "press"
    x.ButtonRelease = "release"
    display_mod = types.ModuleType("Xlib.display")

    class Display:
        def sync(self):
            pass

        def close(self):
            pass

    display_mod.Display = Display
    ext = types.ModuleType("Xlib.ext")
    xtest = types.ModuleType("Xlib.ext.xtest")

    def fake_input(display, evento, botao):
        reg.eventos.append(("fake_input", (evento, botao)))

    xtest.fake_input = fake_input
    xlib.X = x
    xlib.display = display_mod
    xlib.ext = ext
    ext.xtest = xtest
    return {
        "Xlib": xlib,
        "Xlib.X": x,
        "Xlib.display": display_mod,
        "Xlib.ext": ext,
        "Xlib.ext.xtest": xtest,
    }


def _fake_gi(reg, dbus_ok=False):
    gi = types.ModuleType("gi")
    gi.require_version = lambda *a, **k: None
    repo = types.ModuleType("gi.repository")

    gtk = MagicMock(name="Gtk")
    gtk.events_pending.return_value = False
    gdk = MagicMock(name="Gdk")
    gdk.KEY_q, gdk.KEY_Q, gdk.KEY_Escape = 113, 81, 65307

    pixbuf_mod = MagicMock(name="GdkPixbuf")

    def new_from_bytes(_bytes, _cs, _alpha, _bits, largura, altura, _stride):
        reg.pixbufs.append((largura, altura))
        return MagicMock()

    pixbuf_mod.Pixbuf.new_from_bytes.side_effect = new_from_bytes
    glib = MagicMock(name="GLib")
    gio = MagicMock(name="Gio")
    if not dbus_ok:
        gio.bus_get_sync.side_effect = RuntimeError("sem D-Bus no teste")

    repo.Gdk, repo.GdkPixbuf, repo.Gio, repo.GLib, repo.Gtk = gdk, pixbuf_mod, gio, glib, gtk
    gi.repository = repo
    return {"gi": gi, "gi.repository": repo}


def _fake_htm(roteiro, reg):
    """Substitui o HandTrackingModule: devolve as mãos do roteiro, quadro a quadro."""
    htm = types.ModuleType("HandTrackingModule")

    class handDetector:
        def __init__(self, *a, **k):
            self.landmarks = []
            self.lmList = []
            self._atual = None

        def findHands(self, img, draw=True):
            idx = reg.quadro_atual
            self._atual = roteiro[idx] if 0 <= idx < len(roteiro) else None
            return img

        def listar_maos(self, img):
            if not self._atual:
                return []
            m = self._atual
            return [{"landmarks": m, "cx": m["cx"], "cy": m["cy"], "bbox": m["bbox"]}]

        def desenhar_mao(self, img, landmarks, cor_linha=None):
            pass

        def findPosition(self, img, handNo=0, draw=True):
            if self.landmarks:
                self.lmList = [list(p) for p in self.landmarks["lm"]]
                return self.lmList, self.landmarks["bbox"]
            self.lmList = []
            return [], []

        def fingersUp(self):
            return list(self.landmarks["dedos"]) if self.landmarks else []

    class detectorPessoas:
        def detectar(self, img):
            return []

    htm.handDetector = handDetector
    htm.detectorPessoas = detectorPessoas
    return htm


class CameraFalsa:
    def __init__(self, roteiro, reg, relogio, gancho):
        self.roteiro = roteiro
        self.reg = reg
        self.relogio = relogio
        self.gancho = gancho
        self.lidos = 0
        self.liberada = False
        self.abertura = True  # leitura durante open_camera

    def isOpened(self):
        return True

    def set(self, *a):
        return True

    def release(self):
        self.liberada = True

    def read(self):
        img = np.full((480, 640, 3), 90, dtype=np.uint8)
        if self.abertura:
            return True, img
        if self.lidos == 0 and self.gancho is not None:
            self.gancho()
        idx = self.lidos
        self.lidos += 1
        self.relogio.avancar()
        self.reg.quadro_atual = idx
        if idx >= len(self.roteiro):
            return False, None
        if self.roteiro[idx] is FALHA:
            return False, None
        return True, img


def executar_gestum(roteiro, monkeypatch, *, gancho=None, libei_ausente=False):
    """Executa o Gestum.py original com o roteiro de quadros e devolve (ns, reg, cam)."""
    reg = Registro()
    relogio = Relogio()

    for nome, mod in {
        **_fake_gi(reg),
        **_fake_xlib(reg),
        "autopy": _fake_autopy(reg),
        "HandTrackingModule": _fake_htm(roteiro, reg),
    }.items():
        monkeypatch.setitem(sys.modules, nome, mod)

    monkeypatch.setattr(time, "time", relogio.time)
    monkeypatch.setattr(time, "sleep", lambda s: None)

    import atexit

    monkeypatch.setattr(atexit, "register", lambda f, *a, **k: reg.atexit.append((f, a)))

    def check_output(*a, **k):
        raise OSError("v4l2-ctl/xrandr indisponíveis no teste")

    monkeypatch.setattr(subprocess, "check_output", check_output)

    if libei_ausente:
        def cdll(nome, *a, **k):
            raise OSError(f"{nome}: cannot open shared object file")
    else:
        def cdll(nome, *a, **k):
            return MagicMock(name=nome)
    monkeypatch.setattr(ctypes, "CDLL", cdll)

    ns = {"__name__": "__main__", "__file__": str(GESTUM)}
    holder = {}

    def gancho_interno():
        if gancho is not None:
            gancho(ns)

    def video_capture(_fonte):
        cam = CameraFalsa(roteiro, reg, relogio, gancho_interno)
        holder["cam"] = cam
        return cam

    monkeypatch.setattr(cv2, "VideoCapture", video_capture)

    # open_camera lê quadros para escolher o dispositivo; depois o laço começa.
    original_print = print

    def marcar_fim_da_abertura(*a, **k):
        if a and isinstance(a[0], str) and a[0].startswith("Câmera em uso") and "cam" in holder:
            holder["cam"].abertura = False
        return original_print(*a, **k)

    ns["print"] = marcar_fim_da_abertura

    codigo = compile(GESTUM.read_text(encoding="utf-8"), str(GESTUM), "exec")
    monkeypatch.chdir(RAIZ)
    exec(codigo, ns)
    return ns, reg, holder.get("cam")


@pytest.fixture
def gestum(monkeypatch):
    def _executar(roteiro, **kw):
        return executar_gestum(roteiro, monkeypatch, **kw)

    return _executar
