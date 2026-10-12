import atexit
import ctypes
import os
import re
import select
import subprocess

import cv2
import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
gi.require_version("Gio", "2.0")
from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk

import numpy as np
from PIL import Image, ImageDraw, ImageFont
import HandTrackingModule as htm
import time
import autopy
import math
from collections import deque
from Xlib import X
from Xlib.display import Display
from Xlib.ext.xtest import fake_input

# Parâmetros
wCam, hCam = 640, 480
preview_scale = 2  # A janela mostra o quadro em dobro
frameR = 8  # Margem fina: a detecção usa quase o quadro inteiro
frameR_top = 8
painel_largura = 420  # Coluna dos comandos, fora da imagem da câmera
smoothening = 3
scroll_sensitivity = 3  # Cliques por quadro no extremo da área. O teto é 10
scroll_threshold = 75  # Distância máxima para ativar a rolagem

# Parâmetros da zona morta da rolagem
scroll_deadzone_center = 50  # Centro da barra (50%)
scroll_deadzone_range = 10  # ±10% de zona morta (faixa de 40% a 60%)
scroll_deadzone_min = scroll_deadzone_center - scroll_deadzone_range  # 40%
scroll_deadzone_max = scroll_deadzone_center + scroll_deadzone_range  # 60%

# Tempo e suavização
pTime = 0
plocX, plocY = 0, 0
clocX, clocY = 0, 0
move_active = False
last_hand = None
cursor_gain = 8  # Pixels do cursor para cada pixel da mão

# Acompanhamento da rolagem
scroll_start_y = 0
scroll_active = False
scroll_position = 50  # Começa no centro (50%)
scroll_history = deque(maxlen=5)  # Suaviza a direção da rolagem
virtual_scroll_y = 0  # Posição vertical virtual do controle de rolagem

# Temporizadores para evitar cliques repetidos
last_left_click = 0
last_right_click = 0
last_double_click = 0
click_cooldown = 0.3  # 300 ms entre um clique e outro

# Estado do arraste
gesto_atual = ""
esquerda_junto = False
drag_active = False
drag_start_pos = None
last_drag_seen = 0
drag_hold_grace = 0.25

def open_camera(width, height):
    """Abre a primeira câmera que entrega um quadro. O índice 0 é a câmera virtual do OBS."""
    logger = cv2.utils.logging
    previous_level = logger.getLogLevel()
    logger.setLogLevel(logger.LOG_LEVEL_ERROR)
    try:
        return _open_first_capture(width, height)
    finally:
        logger.setLogLevel(previous_level)


def _camera_sources():
    """Lista a primeira saída colorida de cada câmera real.

    A do notebook também expõe um sensor cinza em /dev/video5, que aparece preto.
    """
    try:
        text = subprocess.check_output(
            ["v4l2-ctl", "--list-devices"], text=True, stderr=subprocess.DEVNULL
        )
    except (OSError, subprocess.CalledProcessError):
        return list(range(10))

    groups = []
    current = None
    for line in text.splitlines():
        if not line.startswith("\t"):
            current = {"name": line.strip(), "devices": []}
            groups.append(current)
            continue
        path = line.strip()
        if current is not None and path.startswith("/dev/video"):
            current["devices"].append(path)

    sources = []
    for group in groups:
        name = group["name"].lower()
        if "obs" in name or "virtual" in name or not group["devices"]:
            continue
        source = group["devices"][0]
        try:
            fmt = subprocess.check_output(
                ["v4l2-ctl", "-d", source, "--get-fmt-video"],
                text=True,
                stderr=subprocess.DEVNULL,
            )
        except (OSError, subprocess.CalledProcessError):
            continue
        if "GREY" in fmt:
            continue
        sources.append(source)

    sources.sort(key=lambda path: 0 if path.endswith("video1") else 1)
    return sources or list(range(10))


def _frame_has_image(frame):
    return frame is not None and frame.size > 0 and float(frame.mean()) > 12


def _open_first_capture(width, height):
    fallback = None
    for source in _camera_sources():
        camera = cv2.VideoCapture(source)
        if not camera.isOpened():
            camera.release()
            continue
        camera.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        camera.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        brightest = None
        brightest_mean = -1
        for _ in range(12):
            ok, frame = camera.read()
            if not ok or frame is None or frame.size == 0:
                continue
            level = float(frame.mean())
            if level > brightest_mean:
                brightest = frame
                brightest_mean = level
            if _frame_has_image(frame):
                print(f"Câmera em uso: {source} ({frame.shape[1]}x{frame.shape[0]})")
                return camera
        camera.release()
        if brightest is not None and (fallback is None or brightest_mean > fallback[0]):
            fallback = (brightest_mean, source)

    if fallback is not None:
        source = fallback[1]
        camera = cv2.VideoCapture(source)
        camera.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        camera.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        print(f"Câmera em uso: {source} (imagem escura)")
        return camera
    raise SystemExit("Nenhuma câmera com imagem foi encontrada.")


class CameraWindow:
    """Mostra a câmera com GTK. A janela Qt do OpenCV pisca no Wayland."""

    def __init__(self, title):
        self.quit = False
        self._bytes = None
        self.window = Gtk.Window(title=title)
        self.window.set_resizable(False)
        self.image = Gtk.Image()
        self.window.add(self.image)
        self.window.connect("destroy", self._on_destroy)
        self.window.connect("key-press-event", self._on_key)
        self.window.show_all()

    def _on_destroy(self, *_args):
        self.quit = True

    def _on_key(self, _widget, event):
        if event.keyval in (Gdk.KEY_q, Gdk.KEY_Q, Gdk.KEY_Escape):
            self.quit = True
            return True
        return False

    def show(self, bgr):
        if preview_scale != 1:
            bgr = cv2.resize(
                bgr, None, fx=preview_scale, fy=preview_scale, interpolation=cv2.INTER_LINEAR
            )
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        height, width = rgb.shape[:2]
        self._bytes = GLib.Bytes.new(rgb.tobytes())
        pixbuf = GdkPixbuf.Pixbuf.new_from_bytes(
            self._bytes,
            GdkPixbuf.Colorspace.RGB,
            False,
            8,
            width,
            height,
            width * 3,
        )
        self.image.set_from_pixbuf(pixbuf)
        while Gtk.events_pending():
            Gtk.main_iteration_do(False)
        return not self.quit                                                                                                                        

    def close(self):
        if self.window.get_visible():
            self.window.destroy()
            while Gtk.events_pending():
                Gtk.main_iteration_do(False)

# Abre a câmera
cap = open_camera(wCam, hCam)

# Prepara o detector de mão
detector = htm.handDetector(maxHands=2)
pessoas = htm.detectorPessoas()
pessoa_dominante = None
dominante_vista = 0
centro_mao = None
wScr, hScr = autopy.screen.size()


def move_cursor(x, y):
    """Move o cursor. O autopy rejeita a coordenada igual à largura ou à altura."""
    x = min(max(float(x), 0), wScr - 1)
    y = min(max(float(y), 0), hScr - 1)
    autopy.mouse.move(x, y)


class PonteiroWayland:
    """Injeta o mouse no compositor. O autopy só mexe no ponteiro do X11, que o GNOME ignora."""

    BOTAO_ESQUERDO = 0x110
    BOTAO_DIREITO = 0x111

    def __init__(self):
        self.ok = False
        self.emulando = False
        self.ei = None
        self.rel = None
        self.abs = None
        self._seq = 1
        self._sessao = None
        self.lib = ctypes.CDLL("libei.so.1")
        self._preparar_biblioteca()
        try:
            self._conectar()
        except Exception as erro:
            print(f"Cursor do Wayland indisponível: {erro}")

    def _preparar_biblioteca(self):
        lib = self.lib
        vazio = ctypes.c_void_p
        lib.ei_new_sender.restype = vazio
        lib.ei_new_sender.argtypes = [ctypes.c_char_p]
        lib.ei_configure_name.argtypes = [vazio, ctypes.c_char_p]
        lib.ei_setup_backend_fd.argtypes = [vazio, ctypes.c_int]
        lib.ei_setup_backend_fd.restype = ctypes.c_int
        lib.ei_get_fd.argtypes = [vazio]
        lib.ei_get_fd.restype = ctypes.c_int
        lib.ei_dispatch.argtypes = [vazio]
        lib.ei_get_event.argtypes = [vazio]
        lib.ei_get_event.restype = vazio
        lib.ei_event_get_type.argtypes = [vazio]
        lib.ei_event_get_type.restype = ctypes.c_int
        lib.ei_event_get_seat.argtypes = [vazio]
        lib.ei_event_get_seat.restype = vazio
        lib.ei_event_get_device.argtypes = [vazio]
        lib.ei_event_get_device.restype = vazio
        lib.ei_event_unref.argtypes = [vazio]
        lib.ei_seat_ref.argtypes = [vazio]
        lib.ei_seat_ref.restype = vazio
        lib.ei_seat_bind_capabilities.argtypes = [vazio]
        lib.ei_device_ref.argtypes = [vazio]
        lib.ei_device_ref.restype = vazio
        lib.ei_device_unref.argtypes = [vazio]
        lib.ei_device_has_capability.argtypes = [vazio, ctypes.c_int]
        lib.ei_device_has_capability.restype = ctypes.c_bool
        lib.ei_device_start_emulating.argtypes = [vazio, ctypes.c_uint32]
        lib.ei_device_pointer_motion.argtypes = [vazio, ctypes.c_double, ctypes.c_double]
        lib.ei_device_pointer_motion_absolute.argtypes = [vazio, ctypes.c_double, ctypes.c_double]
        lib.ei_device_button_button.argtypes = [vazio, ctypes.c_uint32, ctypes.c_bool]
        lib.ei_device_scroll_discrete.argtypes = [vazio, ctypes.c_int32, ctypes.c_int32]
        lib.ei_device_frame.argtypes = [vazio, ctypes.c_uint64]
        lib.ei_now.argtypes = [vazio]
        lib.ei_now.restype = ctypes.c_uint64
        lib.ei_unref.argtypes = [vazio]

    def _conectar(self):
        barramento = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        area = Gio.DBusProxy.new_sync(
            barramento, Gio.DBusProxyFlags.NONE, None,
            "org.gnome.Mutter.RemoteDesktop",
            "/org/gnome/Mutter/RemoteDesktop",
            "org.gnome.Mutter.RemoteDesktop", None,
        )
        caminho = area.call_sync("CreateSession", None, Gio.DBusCallFlags.NONE, -1, None).unpack()[0]
        self._sessao = Gio.DBusProxy.new_sync(
            barramento, Gio.DBusProxyFlags.NONE, None,
            "org.gnome.Mutter.RemoteDesktop", caminho,
            "org.gnome.Mutter.RemoteDesktop.Session", None,
        )
        self._sessao.call_sync("Start", None, Gio.DBusCallFlags.NONE, -1, None)
        self._descritores = None
        resposta, self._descritores = self._sessao.call_with_unix_fd_list_sync(
            "ConnectToEIS",
            GLib.Variant("(a{sv})", ({},)),
            Gio.DBusCallFlags.NONE, -1, None, None,
        )
        descritor = os.dup(self._descritores.get(resposta.unpack()[0]))
        self.ei = self.lib.ei_new_sender(None)
        self.lib.ei_configure_name(self.ei, b"Gestum")
        if self.lib.ei_setup_backend_fd(self.ei, descritor) != 0:
            raise RuntimeError("nao foi possivel ligar o cursor virtual")

        canal = self.lib.ei_get_fd(self.ei)
        for _ in range(40):
            self.despachar()
            if self.rel and self.emulando:
                break
            select.select([canal], [], [], 0.05)
        self.despachar()
        self.ok = bool(self.rel and self.emulando)
        if self.ok:
            print("Cursor do Wayland ativo.")
        else:
            print("Cursor do Wayland não respondeu. O movimento fica só no ponteiro do X11.")

    def despachar(self):
        if not self.ei:
            return
        self.lib.ei_dispatch(self.ei)
        while True:
            evento = self.lib.ei_get_event(self.ei)
            if not evento:
                break
            self._tratar(evento)
            self.lib.ei_event_unref(evento)

    def _tratar(self, evento):
        tipo = self.lib.ei_event_get_type(evento)
        if tipo == 3:
            assento = self.lib.ei_seat_ref(self.lib.ei_event_get_seat(evento))
            # Só o ponteiro relativo. O absoluto duplicava o clique.
            self.lib.ei_seat_bind_capabilities(assento, 1, 16, 32, 0)
            return
        if tipo not in (5, 7, 8):
            return
        dispositivo = self.lib.ei_event_get_device(evento)
        if not dispositivo:
            return
        absoluto = self.lib.ei_device_has_capability(dispositivo, 2)
        relativo = self.lib.ei_device_has_capability(dispositivo, 1) and not absoluto
        campo = "abs" if absoluto else "rel" if relativo else None
        if campo is None:
            return
        if tipo == 7:
            self.emulando = bool(self.abs or self.rel)
            return
        atual = getattr(self, campo)
        if atual != dispositivo:
            if atual:
                self.lib.ei_device_unref(atual)
            setattr(self, campo, self.lib.ei_device_ref(dispositivo))
        if tipo == 8 and campo == "rel":
            self.lib.ei_device_start_emulating(self.rel, self._seq)
            self._seq = (self._seq + 1) & 0xFFFFFFFF
            self.emulando = True

    def _controle(self):
        if self.rel:
            return self.rel
        return self.abs

    def _quadro(self, dispositivo):
        self.lib.ei_device_frame(dispositivo, self.lib.ei_now(self.ei))
        self.despachar()

    def mover_absoluto(self, x, y):
        if not (self.ok and self.emulando and self.abs):
            return False
        self.lib.ei_device_pointer_motion_absolute(self.abs, float(x), float(y))
        self._quadro(self.abs)
        return True

    def mover(self, dx, dy):
        if not (self.ok and self.emulando and self.rel):
            return False
        self.lib.ei_device_pointer_motion(self.rel, float(dx), float(dy))
        self._quadro(self.rel)
        return True

    def botao(self, codigo, pressionado):
        dispositivo = self._controle()
        if not (self.ok and self.emulando and dispositivo):
            return False
        self.lib.ei_device_button_button(dispositivo, codigo, bool(pressionado))
        self._quadro(dispositivo)
        return True

    def clique(self, codigo):
        """Pressiona e solta o botão, como um clique físico."""
        if not self.botao(codigo, True):
            return False
        time.sleep(0.04)
        return self.botao(codigo, False)

    def rolar(self, cliques):
        """Positivo sobe. 120 unidades do libei são um clique da rodinha."""
        dispositivo = self._controle()
        if not (self.ok and self.emulando and dispositivo) or cliques == 0:
            return False
        self.lib.ei_device_scroll_discrete(dispositivo, 0, int(-120 * cliques))
        self._quadro(dispositivo)
        return True

    def encerrar(self):
        if self._sessao is not None:
            try:
                self._sessao.call_sync("Stop", None, Gio.DBusCallFlags.NONE, 1000, None)
            except Exception:
                pass
            self._sessao = None
        if self.ei:
            self.lib.ei_unref(self.ei)
            self.ei = None
        self.ok = False
        self.emulando = False


ponteiro = PonteiroWayland()
atexit.register(ponteiro.encerrar)


def move_by_hand(cam_x, cam_y, starting):
    """Desloca o cursor na mesma direção da mão, a partir de onde ele já está."""
    global last_hand
    if starting or last_hand is None:
        last_hand = (cam_x, cam_y)
        return
    dx = (cam_x - last_hand[0]) * cursor_gain
    dy = (cam_y - last_hand[1]) * cursor_gain
    last_hand = (cam_x, cam_y)
    if dx == 0 and dy == 0:
        return
    if ponteiro.mover(dx, dy):
        return
    pointer_x, pointer_y = autopy.mouse.location()
    move_cursor(pointer_x + dx, pointer_y + dy)


_monitor_cache = []
_monitor_cache_at = 0
_primary_monitor = None
control_monitor = None


def list_monitors():
    """Retorna cada tela física. O tamanho do autopy junta as duas numa só."""
    global _monitor_cache, _monitor_cache_at, _primary_monitor
    now = time.time()
    if _monitor_cache and now - _monitor_cache_at < 5:
        return _monitor_cache
    found = []
    primary = None
    try:
        text = subprocess.check_output(["xrandr", "--query"], text=True, stderr=subprocess.DEVNULL)
        for match in re.finditer(r"connected( primary)? (\d+)x(\d+)\+(\d+)\+(\d+)", text):
            width, height, origin_x, origin_y = (int(value) for value in match.groups()[1:])
            monitor = (origin_x, origin_y, width, height)
            found.append(monitor)
            if match.group(1):
                primary = monitor
    except (OSError, subprocess.CalledProcessError):
        found = []
    if not found:
        found = [(0, 0, int(wScr), int(hScr))]
    _monitor_cache = found
    _primary_monitor = primary or found[0]
    _monitor_cache_at = now
    return found


def monitor_at(x, y, monitors):
    for origin_x, origin_y, width, height in monitors:
        if origin_x <= x < origin_x + width and origin_y <= y < origin_y + height:
            return (origin_x, origin_y, width, height)
    return min(
        monitors,
        key=lambda mon: (x - (mon[0] + mon[2] / 2)) ** 2 + (y - (mon[1] + mon[3] / 2)) ** 2,
    )


def monitor_label(monitor, monitors):
    if len(monitors) < 2:
        return "esta tela"
    ordered = sorted(monitors, key=lambda mon: (mon[0], mon[1]))
    if monitor == ordered[0]:
        return "tela da esquerda"
    if monitor == ordered[-1]:
        return "tela da direita"
    return "outra tela"


def map_hand_to_screen(cam_x, cam_y, lock_current):
    """Mapeia a mão na tela onde o cursor já está, não no desktop inteiro."""
    global control_monitor, plocX, plocY
    monitors = list_monitors()
    just_locked = control_monitor is None or lock_current
    if just_locked:
        control_monitor = _primary_monitor or monitors[0]
        log_action("CURSOR", monitor_label(control_monitor, monitors))

    previous_monitor = control_monitor
    origin_x, origin_y, width, height = control_monitor
    if cam_x <= frameR + 25:
        neighbors = [
            mon for mon in monitors
            if mon[0] + mon[2] <= origin_x + 2 and mon[1] < origin_y + height and mon[1] + mon[3] > origin_y
        ]
        if neighbors:
            control_monitor = max(neighbors, key=lambda mon: mon[0])
    elif cam_x >= wCam - frameR - 25:
        neighbors = [
            mon for mon in monitors
            if mon[0] >= origin_x + width - 2 and mon[1] < origin_y + height and mon[1] + mon[3] > origin_y
        ]
        if neighbors:
            control_monitor = min(neighbors, key=lambda mon: mon[0])

    switched = control_monitor != previous_monitor
    if switched:
        origin_x, origin_y, width, height = control_monitor
        log_action("CURSOR", monitor_label(control_monitor, monitors))

    x = np.interp(cam_x, (frameR, wCam - frameR), (origin_x, origin_x + width - 1))
    y = np.interp(cam_y, (frameR_top, hCam - frameR), (origin_y, origin_y + height - 1))
    if just_locked or switched:
        plocX, plocY = x, y
    return x, y, monitor_label(control_monitor, monitors)


def release_drag(reason=""):
    """Solta o botão esquerdo se um arraste estiver em andamento."""
    global drag_active, drag_start_pos
    if not drag_active:
        return
    drag_active = False
    drag_start_pos = None
    if not ponteiro.botao(PonteiroWayland.BOTAO_ESQUERDO, False):
        autopy.mouse.toggle(down=False)
    log_action("ARRASTE ENCERRADO", reason)


atexit.register(release_drag, "interrompido")
print("Tamanho da tela:", wScr, hScr)
print("Gestum iniciado!")
print("Controles:")
print("- Mão aberta: parado")
print("- Só o indicador: mover o cursor")
print("- Indicador + médio juntos: clique esquerdo")
print("- Indicador + médio + anelar: clique direito")
print("- Médio + anelar + mínimo: clique duplo")
print("- Médio + anelar: rolagem")
print("- Indicador + polegar, os outros fechados: arrastar")
print("- Pressione 'q' para sair")
print(f"- Zona morta da rolagem: {scroll_deadzone_min}%–{scroll_deadzone_max}%")


def calculate_distance(point1, point2):
    """Calcula a distância euclidiana entre dois pontos."""
    return math.sqrt((point1[0] - point2[0]) ** 2 + (point1[1] - point2[1]) ** 2)


def draw_scroll_bar(img, scroll_pos, bar_x, bar_y_start, bar_height, bar_width=14):
    """Desenha a barra de rolagem no painel, fora da câmera."""
    cv2.rectangle(img, (bar_x, bar_y_start), (bar_x + bar_width, bar_y_start + bar_height),
                  (60, 60, 60), -1)
    deadzone_start = int((scroll_deadzone_min / 100) * bar_height)
    deadzone_end = int((scroll_deadzone_max / 100) * bar_height)
    cv2.rectangle(img, (bar_x, bar_y_start + deadzone_start),
                  (bar_x + bar_width, bar_y_start + deadzone_end),
                  (0, 100, 100), -1)
    cv2.rectangle(img, (bar_x, bar_y_start), (bar_x + bar_width, bar_y_start + bar_height),
                  (255, 255, 255), 1)
    pos_height = int((scroll_pos / 100) * bar_height)
    indicator_size = 12
    cv2.rectangle(img, (bar_x - 2, bar_y_start + pos_height - indicator_size // 2),
                  (bar_x + bar_width + 2, bar_y_start + pos_height + indicator_size // 2),
                  (0, 255, 0), -1)


_fontes = {}


def _fonte(tamanho):
    if tamanho not in _fontes:
        _fontes[tamanho] = ImageFont.truetype(
            "/usr/share/fonts/lato-fonts/Lato-Regular.ttf", tamanho
        )
    return _fontes[tamanho]


def escrever_textos(img, linhas):
    """Desenha texto com acentos. A fonte do OpenCV não aceita ç, ã nem é."""
    imagem = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
    desenho = ImageDraw.Draw(imagem)
    for texto, x, y, cor, tamanho in linhas:
        desenho.text((x, y), texto, font=_fonte(tamanho), fill=(int(cor[2]), int(cor[1]), int(cor[0])))
    img[:] = cv2.cvtColor(np.asarray(imagem), cv2.COLOR_RGB2BGR)


def _desenhar_mao(desenho, x, y, dedos, cor, pinca=False):
    """Mão vista no espelho da câmera: polegar à esquerda, mínimo à direita."""
    apagado = (90, 90, 90)
    desenho.ellipse((x + 7, y + 16, x + 29, y + 33), fill=(55, 55, 55), outline=cor)
    bases = [(x + 9, y + 20), (x + 13, y + 16), (x + 18, y + 15), (x + 23, y + 16), (x + 27, y + 18)]
    if pinca:
        pontas = [(x + 14, y + 8), (x + 16, y + 6), (x + 18, y + 12), (x + 23, y + 13), (x + 27, y + 15)]
        ativos = (True, True, False, False, False)
    else:
        pontas = [
            (x + 2, y + 12),
            (x + 12, y + 1),
            (x + 18, y + 0),
            (x + 24, y + 2),
            (x + 30, y + 7),
        ]
        ativos = dedos
    for ligado, base, ponta in zip(ativos, bases, pontas):
        if not ligado and not pinca:
            ponta = (base[0], base[1] - 3)
        desenho.line((base, ponta), fill=cor if ligado else apagado, width=3)
        desenho.ellipse((ponta[0] - 2, ponta[1] - 2, ponta[0] + 2, ponta[1] + 2), fill=cor if ligado else apagado)


def _gestos_do_painel():
    """Polegar, indicador, médio, anelar, mínimo. A pinça junta indicador e polegar."""
    return [
        ("parado", "Mão aberta: parado", (255, 255, 255), (1, 1, 1, 1, 1), False),
        ("mover", "Indicador: mover o cursor", (0, 255, 255), (0, 1, 0, 0, 0), False),
        ("esquerdo", "Indicador + médio juntos: clique esquerdo", (0, 255, 0), (0, 1, 1, 0, 0), False),
        ("direito", "Indicador + médio + anelar: clique direito", (0, 100, 255), (0, 1, 1, 1, 0), False),
        ("duplo", "Médio + anelar + mínimo: clique duplo", (255, 0, 255), (0, 0, 1, 1, 1), False),
        ("rolagem", "Médio + anelar: rolagem", (100, 255, 100), (0, 0, 1, 1, 0), False),
        ("arraste", "Indicador + polegar, os outros fechados: arrastar", (255, 255, 0), (1, 1, 0, 0, 0), True),
    ]


def desenhar_painel(fps):
    """Coluna de comandos ao lado da câmera. A imagem da detecção fica sem esse texto."""
    painel = np.full((hCam, painel_largura, 3), 18, dtype=np.uint8)
    barra_x = painel_largura - 26
    draw_scroll_bar(painel, scroll_position, barra_x, 40, hCam - 88)

    imagem = Image.fromarray(cv2.cvtColor(painel, cv2.COLOR_BGR2RGB))
    desenho = ImageDraw.Draw(imagem)
    desenho.text((12, 8), "GESTUM", font=_fonte(18), fill=(255, 255, 255))
    y = 36
    for chave, texto, cor_bgr, dedos, pinca in _gestos_do_painel():
        cor = (int(cor_bgr[2]), int(cor_bgr[1]), int(cor_bgr[0]))
        if gesto_atual == chave:
            desenho.rectangle((4, y - 2, barra_x - 10, y + 32), fill=(40, 40, 40))
        _desenhar_mao(desenho, 8, y, dedos, cor, pinca)
        desenho.text((46, y + 8), texto, font=_fonte(13), fill=cor)
        y += 34
        if chave == "rolagem":
            desenho.text((46, y), "Mão no alto: rolar para cima", font=_fonte(12), fill=cor)
            y += 15
            desenho.text((46, y), "Mão embaixo: rolar para baixo", font=_fonte(12), fill=cor)
            y += 16
    estados = {
        "parado": "Parado",
        "mover": "Movendo o cursor",
        "esquerdo": "Clique esquerdo" if esquerda_junto else "Mirando",
        "direito": "Clique direito",
        "duplo": "Clique duplo",
        "rolagem": f"Rolagem {int(scroll_position)}%",
        "arraste": "Arrastando",
    }
    desenho.text((12, hCam - 46), estados.get(gesto_atual, "Aguardando a mão"), font=_fonte(14), fill=(255, 255, 255))
    desenho.text((12, hCam - 26), f"{int(fps)} quadros/s    q para sair", font=_fonte(13), fill=(180, 180, 180))
    return cv2.cvtColor(np.asarray(imagem), cv2.COLOR_RGB2BGR)


def montar_tela(camera, fps):
    """Junta a câmera, só com a visão, e o painel de comandos à direita."""
    tela = np.zeros((hCam, wCam + painel_largura, 3), dtype=np.uint8)
    tela[:, :wCam] = camera
    tela[:, wCam:] = desenhar_painel(fps)
    return tela


def usar_gesto(nome):
    """Marca o gesto atual e avisa quando ele acabou de começar."""
    global gesto_atual
    novo = gesto_atual != nome
    gesto_atual = nome
    return novo


def log_action(action, details=""):
    """Registra a ação com o horário."""
    timestamp = time.strftime("%H:%M:%S", time.localtime())
    print(f"[{timestamp}] {action} {details}")


def scroll_wheel(clicks):
    """Rola a rodinha no cursor atual. Positivo sobe, negativo desce."""
    clicks = int(clicks)
    if clicks == 0:
        return
    if ponteiro.rolar(clicks):
        return
    button = 4 if clicks > 0 else 5
    display = Display()
    try:
        for _ in range(abs(clicks)):
            fake_input(display, X.ButtonPress, button)
            fake_input(display, X.ButtonRelease, button)
        display.sync()
    finally:
        display.close()


_cliques_recentes = deque()  # (instante, quantidade) na última janela de 1 s
LIMITE_POR_QUADRO = 10
LIMITE_POR_SEGUNDO = 100


def _cliques_da_distancia(distancia):
    """Um clique na borda da zona morta e scroll_sensitivity no extremo, com teto de 10."""
    teto = max(1, min(LIMITE_POR_QUADRO, int(scroll_sensitivity)))
    fracao = min(max(distancia, 0), 40) / 40
    return max(1, min(teto, int(round(1 + fracao * (teto - 1)))))


def _cliques_permitidos(pedido):
    """Respeita o teto do quadro e o de 100 cliques na última janela de um segundo."""
    agora = time.time()
    pedido = max(0, min(LIMITE_POR_QUADRO, int(pedido)))
    while _cliques_recentes and agora - _cliques_recentes[0][0] >= 1:
        _cliques_recentes.popleft()
    usado = sum(quantidade for _, quantidade in _cliques_recentes)
    pedido = min(pedido, max(0, LIMITE_POR_SEGUNDO - usado))
    if pedido:
        _cliques_recentes.append((agora, pedido))
    return pedido


def perform_smart_scroll(scroll_position):
    """Rola com zona morta e velocidade variável."""
    if scroll_deadzone_min <= scroll_position <= scroll_deadzone_max:
        return "deadzone"

    if scroll_position < scroll_deadzone_min:
        distancia = scroll_deadzone_min - scroll_position
        sentido = 1
        direcao = "up"
        rotulo = "ROLAR PARA CIMA"
    elif scroll_position > scroll_deadzone_max:
        distancia = scroll_position - scroll_deadzone_max
        sentido = -1
        direcao = "down"
        rotulo = "ROLAR PARA BAIXO"
    else:
        return "none"

    cliques = _cliques_permitidos(_cliques_da_distancia(distancia))
    try:
        scroll_wheel(sentido * cliques)
        log_action(rotulo, f"Velocidade: {cliques}, Pos: {scroll_position:.1f}%")
        return direcao
    except Exception as e:
        log_action("ERRO NA ROLAGEM", str(e))
        return "none"


def area_mao(mao):
    x1, y1, x2, y2 = mao["bbox"]
    return max(1, (x2 - x1) * (y2 - y1))


def escolher_mao(rostos, maos, dominante, agora):
    """Usa a mão da pessoa mais perto. Na imagem, essa mão é a maior."""
    global pessoa_dominante, dominante_vista
    prioritaria = rostos[0] if rostos else None
    if not maos:
        if agora - dominante_vista > 0.5:
            pessoa_dominante = None
        return None, prioritaria

    ordenadas = sorted(maos, key=area_mao, reverse=True)
    maior = ordenadas[0]
    if prioritaria is None or len(ordenadas) == 1 or area_mao(maior) >= area_mao(ordenadas[1]) * 1.25:
        escolhida = maior
    else:
        escolhida = min(
            maos,
            key=lambda mao: math.hypot(prioritaria["cx"] - mao["cx"], prioritaria["cy"] - mao["cy"]),
        )
    pessoa_dominante = prioritaria
    dominante_vista = agora
    return escolhida, prioritaria


preview = CameraWindow("Gestum")

# Laço principal
while True:
    ponteiro.despachar()
    success, img = cap.read()
    if not success:
        print("Nao foi possivel ler a camera")
        break

    # Espelha a imagem para o movimento acompanhar a mão
    img = cv2.flip(img, 1)
    rostos = pessoas.detectar(img)
    detector.findHands(img, draw=False)
    mao_escolhida, pessoa_principal = escolher_mao(rostos, detector.listar_maos(img), pessoa_dominante, time.time())
    detector.landmarks = mao_escolhida["landmarks"] if mao_escolhida else []
    if mao_escolhida:
        detector.desenhar_mao(img, mao_escolhida["landmarks"])
    lmList, bbox = detector.findPosition(img, draw=bool(mao_escolhida))
    if mao_escolhida and centro_mao is not None:
        salto = math.hypot(mao_escolhida["cx"] - centro_mao[0], mao_escolhida["cy"] - centro_mao[1])
        if salto > 180:
            release_drag("troca de pessoa")
            gesto_atual = ""
            last_hand = None
            esquerda_junto = False
    centro_mao = (mao_escolhida["cx"], mao_escolhida["cy"]) if mao_escolhida else None

    for indice, rosto in enumerate(rostos):
        principal = pessoa_principal is not None and rosto is pessoa_principal
        cor = (0, 220, 0) if principal else (130, 130, 130)
        cv2.rectangle(img, (rosto["x"], rosto["y"]), (rosto["x"] + rosto["w"], rosto["y"] + rosto["h"]), cor, 2)
        cv2.putText(
            img,
            "PESSOA 1" if principal else f"PESSOA {indice + 1}",
            (rosto["x"], max(16, rosto["y"] - 8)),
            cv2.FONT_HERSHEY_SIMPLEX, 0.5, cor, 2,
        )

    current_time = time.time()

    # A borda marca a área de detecção. Os comandos ficam no painel, fora dela.
    cv2.rectangle(img, (frameR, frameR_top), (wCam - frameR, hCam - frameR),
                  (255, 0, 255), 2)

    if len(lmList) != 0:
        # Pontas dos dedos
        thumb_tip = lmList[4][1:]  # Ponta do polegar
        index_tip = lmList[8][1:]  # Ponta do indicador
        middle_tip = lmList[12][1:]  # Ponta do médio
        ring_tip = lmList[16][1:]  # Ponta do anelar
        pinky_tip = lmList[20][1:]  # Ponta do mínimo

        # Verifica quais dedos estão levantados
        fingers = detector.fingersUp()
        if len(fingers) < 5:
            fingers = [0, 0, 0, 0, 0]

        # Cada comando depende de quais dedos estão levantados.
        # A mão aberta fica parada, para não disparar clique nem arraste.
        polegar, indicador, medio, anelar, minimo = fingers
        thumb_index_dist = calculate_distance(thumb_tip, index_tip)
        starting_move = not move_active
        move_active = False
        outros_fechados = not medio and not anelar and not minimo

        # Arraste: pinça do indicador com o polegar e os outros dedos fechados.
        pinch_now = (
            indicador and polegar and outros_fechados and
            thumb_index_dist < (90 if drag_active else 50)
        )
        if pinch_now:
            last_drag_seen = current_time
        holding_drag = drag_active and (pinch_now or current_time - last_drag_seen <= drag_hold_grace)
        mao_aberta = indicador and medio and anelar and minimo
        outro_comando = (
            mao_aberta
            or (indicador and outros_fechados)
            or (indicador and medio and not minimo)
            or (medio and anelar and minimo and not indicador)
            or (medio and anelar and not indicador and not minimo)
        )
        if drag_active and not pinch_now and outro_comando:
            release_drag("outro gesto")
            holding_drag = False

        if mao_aberta:
            usar_gesto("parado")
            esquerda_junto = False
            if drag_active:
                release_drag("mão aberta")
            scroll_active = False
            last_hand = None

        elif pinch_now or holding_drag:
            usar_gesto("arraste")
            if pinch_now:
                move_by_hand(index_tip[0], index_tip[1], starting=not drag_active)
                if not drag_active:
                    if not ponteiro.botao(PonteiroWayland.BOTAO_ESQUERDO, True):
                        autopy.mouse.toggle(down=True)
                    drag_active = True
                    drag_start_pos = (index_tip[0], index_tip[1])
                    log_action("ARRASTE INICIADO", f"Em: {drag_start_pos}")

            cv2.circle(img, index_tip, 18, (255, 255, 0), cv2.FILLED)
            cv2.circle(img, thumb_tip, 18, (255, 255, 0), cv2.FILLED)
            cv2.line(img, index_tip, thumb_tip, (255, 255, 0), 4)
            if drag_start_pos:
                cv2.line(img, drag_start_pos, index_tip, (255, 255, 0), 2)
            scroll_active = False

        # 1. Movimento: só o indicador levantado
        elif indicador and outros_fechados:
            usar_gesto("mover")
            move_by_hand(index_tip[0], index_tip[1], starting=starting_move)
            move_active = True

            cv2.circle(img, index_tip, 15, (0, 255, 255), cv2.FILLED)
            scroll_active = False

        # 2. Clique esquerdo: indicador e médio abertos movem o cursor.
        # O clique sai uma vez, quando as duas pontas se encostam.
        elif indicador and medio and not anelar and not minimo:
            comecou = usar_gesto("esquerdo")
            meio = ((index_tip[0] + middle_tip[0]) // 2, (index_tip[1] + middle_tip[1]) // 2)
            move_by_hand(meio[0], meio[1], starting=comecou)
            move_active = True
            distancia = calculate_distance(index_tip, middle_tip)
            junto = distancia < 40
            if junto and not esquerda_junto and current_time - last_left_click > click_cooldown:
                if not ponteiro.clique(PonteiroWayland.BOTAO_ESQUERDO):
                    autopy.mouse.click(autopy.mouse.Button.LEFT)
                last_left_click = current_time
                log_action("CLIQUE ESQUERDO")
            esquerda_junto = junto

            cv2.circle(img, index_tip, 15, (0, 255, 0), cv2.FILLED)
            cv2.circle(img, middle_tip, 15, (0, 255, 0), cv2.FILLED)
            cv2.line(img, index_tip, middle_tip, (0, 255, 0), 3)

        # 3. Clique direito: indicador, médio e anelar. O mínimo fica fechado.
        elif indicador and medio and anelar and not minimo:
            if usar_gesto("direito") and current_time - last_right_click > click_cooldown:
                if not (
                    ponteiro.botao(PonteiroWayland.BOTAO_DIREITO, True)
                    and ponteiro.botao(PonteiroWayland.BOTAO_DIREITO, False)
                ):
                    autopy.mouse.click(autopy.mouse.Button.RIGHT)
                last_right_click = current_time
                log_action("CLIQUE DIREITO")

            # Retorno visual
            cv2.circle(img, thumb_tip, 15, (0, 100, 255), cv2.FILLED)
            cv2.circle(img, middle_tip, 15, (0, 100, 255), cv2.FILLED)
            cv2.line(img, thumb_tip, middle_tip, (0, 100, 255), 3)

        # 4. Clique duplo: médio, anelar e mínimo. O indicador fica fechado.
        elif medio and anelar and minimo and not indicador:
            if usar_gesto("duplo") and current_time - last_double_click > click_cooldown:
                if ponteiro.ok:
                    ponteiro.botao(PonteiroWayland.BOTAO_ESQUERDO, True)
                    ponteiro.botao(PonteiroWayland.BOTAO_ESQUERDO, False)
                    time.sleep(0.1)
                    ponteiro.botao(PonteiroWayland.BOTAO_ESQUERDO, True)
                    ponteiro.botao(PonteiroWayland.BOTAO_ESQUERDO, False)
                else:
                    autopy.mouse.click(autopy.mouse.Button.LEFT)
                    time.sleep(0.1)
                    autopy.mouse.click(autopy.mouse.Button.LEFT)
                last_double_click = current_time
                log_action("CLIQUE DUPLO")

            # Retorno visual
            cv2.circle(img, middle_tip, 12, (255, 0, 255), cv2.FILLED)
            cv2.circle(img, ring_tip, 12, (255, 0, 255), cv2.FILLED)
            cv2.circle(img, pinky_tip, 12, (255, 0, 255), cv2.FILLED)

        # 5. Rolagem: médio e anelar. Suba ou desça a mão.
        elif medio and anelar and not indicador and not minimo:
            usar_gesto("rolagem")
            hand_center_y = (middle_tip[1] + ring_tip[1]) // 2
            # Converte a altura da mão em porcentagem de 0 a 100
            scroll_position = np.interp(hand_center_y, (frameR_top, hCam - frameR), (0, 100))
            scroll_position = max(0, min(100, scroll_position))  # Limita entre 0 e 100

            # Executa a rolagem, respeitando a zona morta
            perform_smart_scroll(scroll_position)

            # Retorno visual da rolagem
            cv2.circle(img, middle_tip, 15, (100, 255, 100), cv2.FILLED)
            cv2.circle(img, ring_tip, 15, (100, 255, 100), cv2.FILLED)
            cv2.line(img, middle_tip, ring_tip, (100, 255, 100), 3)
            scroll_active = True

        else:
            usar_gesto("")
            esquerda_junto = False
            if drag_active and current_time - last_drag_seen > drag_hold_grace:
                release_drag()
            scroll_active = False
            last_hand = None

    else:
        scroll_active = False
        last_hand = None
        gesto_atual = ""
        if drag_active and current_time - last_drag_seen > drag_hold_grace:
            release_drag("mão perdida")

    if scroll_active and len(lmList) != 0:
        hand_center_y = (lmList[12][2] + lmList[16][2]) // 2  # Altura do médio e do anelar
        scroll_position = np.interp(hand_center_y, (frameR_top, hCam - frameR), (0, 100))
        scroll_position = max(0, min(100, scroll_position))

    cTime = time.time()
    if cTime - pTime != 0:
        fps = 1 / (cTime - pTime)
    else:
        fps = 0
    pTime = cTime

    if not preview.show(montar_tela(img, fps)):
        log_action("GESTUM ENCERRADO")
        break

# Encerramento
release_drag("programa encerrado")
preview.close()
cap.release()
