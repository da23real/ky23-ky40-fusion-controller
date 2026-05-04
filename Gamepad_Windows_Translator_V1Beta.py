"""
Gamepad Windows Translator V4.2
Windows gamepad USB -> mouse/keyboard for Fusion 360 style navigation.

Mapping default:
- Left joystick ABS_X / ABS_Y = Shift + middle mouse + mouse movement (Fusion orbit)
- D-pad ABS_HAT0X / ABS_HAT0Y = middle mouse + mouse movement (simple orbit)
- Right joystick ABS_RX / ABS_RY = normal mouse movement
- LT ABS_Z / RT ABS_RZ = mouse wheel zoom
- X BTN_WEST = left click held while button held
- B BTN_EAST = right click held while button held
- Y BTN_NORTH = manual cursor catch-up (optional)
- Left stick click BTN_THUMBL = toggle left joystick speed mode
- Right stick click BTN_THUMBR = toggle right joystick speed mode

Dependencies:
  py -3.12 -m pip install inputs pyautogui
"""

import ctypes
import os
import sys
import threading
import time
import queue
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

APP_VERSION = "V4.2"
APP_TITLE = f"Gamepad Windows Translator {APP_VERSION}"
LOCK_NAME = "Global\\GamepadWindowsTranslator_V4_SingleInstance"

try:
    from inputs import get_gamepad
except Exception as exc:
    get_gamepad = None
    INPUTS_IMPORT_ERROR = exc
else:
    INPUTS_IMPORT_ERROR = None

try:
    import pyautogui
except Exception as exc:
    pyautogui = None
    PYAUTOGUI_IMPORT_ERROR = exc
else:
    PYAUTOGUI_IMPORT_ERROR = None

# Safety-ish pyautogui settings: fail-safe off because cursor clamp handles screen borders.
if pyautogui:
    pyautogui.FAILSAFE = False
    pyautogui.PAUSE = 0


def now_str():
    return time.strftime("%H:%M:%S")


def clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


def screen_size():
    if pyautogui:
        try:
            return pyautogui.size()
        except Exception:
            pass
    return (1920, 1080)


class SingleInstance:
    def __init__(self):
        self.handle = None
        self.already_running = False
        if sys.platform == "win32":
            kernel32 = ctypes.windll.kernel32
            self.handle = kernel32.CreateMutexW(None, False, LOCK_NAME)
            self.already_running = kernel32.GetLastError() == 183

    def release(self):
        if self.handle and sys.platform == "win32":
            try:
                ctypes.windll.kernel32.ReleaseMutex(self.handle)
                ctypes.windll.kernel32.CloseHandle(self.handle)
            except Exception:
                pass
            self.handle = None


class HoldOutput:
    """Tracks Windows output states to avoid stuck buttons."""
    def __init__(self, log_cb):
        self.log = log_cb
        self.middle = False
        self.shift = False
        self.left = False
        self.right = False

    def _safe(self, fn, *args, **kwargs):
        if not pyautogui:
            return
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            self.log(f"OUT ERROR {exc!r}")

    def set_middle(self, wanted):
        if wanted and not self.middle:
            self._safe(pyautogui.mouseDown, button="middle")
            self.middle = True
            self.log("OUT middleDown")
        elif not wanted and self.middle:
            self._safe(pyautogui.mouseUp, button="middle")
            self.middle = False
            self.log("OUT middleUp")

    def set_shift(self, wanted):
        if wanted and not self.shift:
            self._safe(pyautogui.keyDown, "shift")
            self.shift = True
            self.log("OUT shiftDown")
        elif not wanted and self.shift:
            self._safe(pyautogui.keyUp, "shift")
            self.shift = False
            self.log("OUT shiftUp")

    def set_left(self, wanted):
        if wanted and not self.left:
            self._safe(pyautogui.mouseDown, button="left")
            self.left = True
            self.log("OUT leftDown")
        elif not wanted and self.left:
            self._safe(pyautogui.mouseUp, button="left")
            self.left = False
            self.log("OUT leftUp")

    def set_right(self, wanted):
        if wanted and not self.right:
            self._safe(pyautogui.mouseDown, button="right")
            self.right = True
            self.log("OUT rightDown")
        elif not wanted and self.right:
            self._safe(pyautogui.mouseUp, button="right")
            self.right = False
            self.log("OUT rightUp")

    def release_all(self):
        self.set_left(False)
        self.set_right(False)
        self.set_middle(False)
        self.set_shift(False)


class App:
    def __init__(self, root):
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry("940x620")
        self.root.minsize(760, 480)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        self.single = SingleInstance()
        if self.single.already_running:
            if not messagebox.askyesno("Instance déjà ouverte", "Une autre instance semble déjà ouverte.\n\nContinuer quand même ?"):
                self.root.after(50, self.root.destroy)
                return

        self.event_q = queue.Queue()
        self.state = {
            # axes
            "ABS_X": 0, "ABS_Y": 0, "ABS_RX": 0, "ABS_RY": 0,
            "ABS_Z": 0, "ABS_RZ": 0,
            "ABS_HAT0X": 0, "ABS_HAT0Y": 0,
            # buttons
            "BTN_WEST": 0, "BTN_EAST": 0, "BTN_NORTH": 0, "BTN_SOUTH": 0,
            "BTN_THUMBL": 0, "BTN_THUMBR": 0,
            "BTN_TL": 0, "BTN_TR": 0,
        }
        self.prev_btn = dict(self.state)

        # UI vars, defaults from user's screenshot
        self.actions_enabled = tk.BooleanVar(value=True)
        self.profile_var = tk.StringVar(value="FUSION")
        self.deadzone_var = tk.IntVar(value=100)
        self.clamp_screen_var = tk.BooleanVar(value=True)
        self.raw_log_var = tk.BooleanVar(value=False)

        self.lx_inv_x = tk.BooleanVar(value=False)
        self.lx_inv_y = tk.BooleanVar(value=True)
        self.lx_min = tk.DoubleVar(value=2.0)
        self.lx_max = tk.DoubleVar(value=16.0)
        self.lx_fast_min = tk.DoubleVar(value=0.5)
        self.lx_fast_max = tk.DoubleVar(value=2.0)
        self.lx_auto_catchup = tk.BooleanVar(value=True)
        self.y_manual_catchup = tk.BooleanVar(value=False)
        self.lx_fast_mode = False

        self.rx_inv_x = tk.BooleanVar(value=False)
        self.rx_inv_y = tk.BooleanVar(value=True)
        self.rx_min = tk.DoubleVar(value=2.0)
        self.rx_max = tk.DoubleVar(value=32.0)
        self.rx_fast_min = tk.DoubleVar(value=0.2)
        self.rx_fast_max = tk.DoubleVar(value=1.0)
        self.rx_fast_mode = False

        self.zoom_invert = tk.BooleanVar(value=True)
        self.lt_rt_threshold = tk.IntVar(value=10)
        self.lt_rt_repeat = tk.IntVar(value=10)
        self.scroll_step = tk.IntVar(value=50)

        self.dpad_inv_x = tk.BooleanVar(value=False)
        self.dpad_inv_y = tk.BooleanVar(value=False)
        self.dpad_speed = tk.DoubleVar(value=14.0)

        self.status_var = tk.StringVar(value="Démarrage...")
        self.raw_var = tk.StringVar(value="RAW ...")
        self.left_mode_var = tk.StringVar(value="Mode vitesse : normal")
        self.right_mode_var = tk.StringVar(value="Mode vitesse : normal")

        self.output = HoldOutput(self.add_log)
        self.running = True
        self.reader_thread = None
        self.last_engine_log = 0
        self.last_scroll = 0
        self.last_raw_log = 0
        self.catch_dx = 0
        self.catch_dy = 0
        self.left_was_moving = False
        self.dpad_was_moving = False

        self.build_ui()
        self.check_deps()
        self.start_reader()
        self.root.after(15, self.tick)
        self.add_log("DÉMARRAGE V4.2")
        self.add_log("Actions activées au lancement = OUI")

    def build_ui(self):
        root_frame = ttk.Frame(self.root, padding=8)
        root_frame.pack(fill="both", expand=True)

        title = ttk.Label(root_frame, text=APP_TITLE, font=("Segoe UI", 15, "bold"))
        title.pack(anchor="w")
        ttk.Label(root_frame, text="Joy gauche = orbite Shift+molette | Croix = orbite molette | Joy droit = souris | LT/RT = zoom | X/B = clic maintenu").pack(anchor="w", pady=(2, 8))

        top = ttk.Frame(root_frame)
        top.pack(fill="x")
        ttk.Checkbutton(top, text="Activer actions", variable=self.actions_enabled, command=self.on_actions_toggle).pack(side="left")
        ttk.Label(top, text="Profil :").pack(side="left", padx=(18, 4))
        ttk.Combobox(top, textvariable=self.profile_var, values=["FUSION", "OFF"], width=10, state="readonly").pack(side="left")
        ttk.Label(top, textvariable=self.status_var, font=("Segoe UI", 9, "bold")).pack(side="left", padx=16)

        nb = ttk.Notebook(root_frame)
        nb.pack(fill="both", expand=True, pady=8)
        self.tab_left = ttk.Frame(nb, padding=10)
        self.tab_right = ttk.Frame(nb, padding=10)
        self.tab_trig = ttk.Frame(nb, padding=10)
        self.tab_dpad = ttk.Frame(nb, padding=10)
        self.tab_general = ttk.Frame(nb, padding=10)
        nb.add(self.tab_left, text="Joy gauche")
        nb.add(self.tab_right, text="Joy droit")
        nb.add(self.tab_trig, text="LT / RT")
        nb.add(self.tab_dpad, text="Croix")
        nb.add(self.tab_general, text="Général / Debug")

        self.build_left_tab()
        self.build_right_tab()
        self.build_trigger_tab()
        self.build_dpad_tab()
        self.build_general_tab()

    def spin(self, parent, label, var, from_, to_, inc=1, width=8):
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=4)
        ttk.Label(row, text=label, width=28).pack(side="left")
        ttk.Spinbox(row, from_=from_, to=to_, increment=inc, textvariable=var, width=width).pack(side="left")
        return row

    def build_left_tab(self):
        ttk.Label(self.tab_left, text="Joy gauche : orbite Fusion", font=("Segoe UI", 11, "bold")).pack(anchor="w")
        ttk.Label(self.tab_left, text="Action : Shift + clic molette + déplacement souris").pack(anchor="w", pady=(0, 8))
        ttk.Label(self.tab_left, textvariable=self.left_mode_var, font=("Segoe UI", 10, "bold")).pack(anchor="w")
        r = ttk.Frame(self.tab_left); r.pack(anchor="w", pady=6)
        ttk.Checkbutton(r, text="Inverser X", variable=self.lx_inv_x).pack(side="left")
        ttk.Checkbutton(r, text="Inverser Y", variable=self.lx_inv_y).pack(side="left", padx=16)
        self.spin(self.tab_left, "Vitesse min", self.lx_min, 0, 100, 0.1)
        self.spin(self.tab_left, "Vitesse max", self.lx_max, 0, 100, 0.1)
        self.spin(self.tab_left, "Vitesse rapide min", self.lx_fast_min, 0, 100, 0.1)
        self.spin(self.tab_left, "Vitesse rapide max", self.lx_fast_max, 0, 100, 0.1)
        ttk.Label(self.tab_left, text="Clic joystick gauche = alterne normal / rapide").pack(anchor="w", pady=(8, 0))
        ttk.Checkbutton(self.tab_left, text="Rattrapage auto au relâchement", variable=self.lx_auto_catchup).pack(anchor="w", pady=(8, 0))
        ttk.Checkbutton(self.tab_left, text="Y = rattrapage manuel", variable=self.y_manual_catchup).pack(anchor="w")

    def build_right_tab(self):
        ttk.Label(self.tab_right, text="Joy droit : souris normale", font=("Segoe UI", 11, "bold")).pack(anchor="w")
        ttk.Label(self.tab_right, text="Action : déplacement du curseur sans clic").pack(anchor="w", pady=(0, 8))
        ttk.Label(self.tab_right, textvariable=self.right_mode_var, font=("Segoe UI", 10, "bold")).pack(anchor="w")
        r = ttk.Frame(self.tab_right); r.pack(anchor="w", pady=6)
        ttk.Checkbutton(r, text="Inverser X", variable=self.rx_inv_x).pack(side="left")
        ttk.Checkbutton(r, text="Inverser Y", variable=self.rx_inv_y).pack(side="left", padx=16)
        self.spin(self.tab_right, "Vitesse min", self.rx_min, 0, 100, 0.1)
        self.spin(self.tab_right, "Vitesse max", self.rx_max, 0, 100, 0.1)
        self.spin(self.tab_right, "Vitesse rapide min", self.rx_fast_min, 0, 100, 0.1)
        self.spin(self.tab_right, "Vitesse rapide max", self.rx_fast_max, 0, 100, 0.1)
        ttk.Label(self.tab_right, text="Clic joystick droit = alterne normal / rapide").pack(anchor="w", pady=(8, 0))
        ttk.Label(self.tab_right, text="X maintenu = clic gauche maintenu").pack(anchor="w")
        ttk.Label(self.tab_right, text="B maintenu = clic droit maintenu").pack(anchor="w")

    def build_trigger_tab(self):
        ttk.Label(self.tab_trig, text="LT / RT : zoom molette", font=("Segoe UI", 11, "bold")).pack(anchor="w")
        ttk.Checkbutton(self.tab_trig, text="Inverser zoom LT/RT", variable=self.zoom_invert).pack(anchor="w", pady=8)
        self.spin(self.tab_trig, "Seuil LT/RT", self.lt_rt_threshold, 0, 255, 1)
        self.spin(self.tab_trig, "Repeat LT/RT ms", self.lt_rt_repeat, 1, 500, 1)
        self.spin(self.tab_trig, "Pas scroll", self.scroll_step, 1, 200, 1)
        ttk.Label(self.tab_trig, text="Note : si Fusion zoome à l'envers, coche/décoche Inverser zoom LT/RT.").pack(anchor="w", pady=(12, 0))

    def build_dpad_tab(self):
        ttk.Label(self.tab_dpad, text="Croix directionnelle : orbite simple", font=("Segoe UI", 11, "bold")).pack(anchor="w")
        ttk.Label(self.tab_dpad, text="Action : clic molette + déplacement souris, sans Shift, sans rattrapage auto").pack(anchor="w", pady=(0, 8))
        r = ttk.Frame(self.tab_dpad); r.pack(anchor="w", pady=6)
        ttk.Checkbutton(r, text="Inverser X", variable=self.dpad_inv_x).pack(side="left")
        ttk.Checkbutton(r, text="Inverser Y", variable=self.dpad_inv_y).pack(side="left", padx=16)
        self.spin(self.tab_dpad, "Vitesse croix", self.dpad_speed, 0, 100, 0.1)

    def build_general_tab(self):
        ttk.Label(self.tab_general, text="Réglage général", font=("Segoe UI", 11, "bold")).pack(anchor="w")
        self.spin(self.tab_general, "Zone morte", self.deadzone_var, 0, 20000, 50)
        ttk.Checkbutton(self.tab_general, text="Clamp écran : empêcher le curseur de sortir de l'écran", variable=self.clamp_screen_var).pack(anchor="w", pady=6)
        ttk.Button(self.tab_general, text="Relâcher toutes les sorties", command=self.output.release_all).pack(anchor="w", pady=8)

        dbg = ttk.LabelFrame(self.tab_general, text="Debug", padding=8)
        dbg.pack(fill="both", expand=True, pady=8)
        ttk.Checkbutton(dbg, text="Journal inputs bruts", variable=self.raw_log_var).pack(anchor="w")
        ttk.Label(dbg, textvariable=self.raw_var).pack(anchor="w", pady=4)
        btns = ttk.Frame(dbg); btns.pack(fill="x", pady=4)
        ttk.Button(btns, text="Copier journal", command=self.copy_log).pack(side="left")
        ttk.Button(btns, text="Enregistrer journal", command=self.save_log).pack(side="left", padx=6)
        ttk.Button(btns, text="Effacer", command=self.clear_log).pack(side="left")
        self.log_text = tk.Text(dbg, height=14, wrap="word")
        self.log_text.pack(fill="both", expand=True, pady=(6,0))

    def add_log(self, msg):
        line = f"[{now_str()}] {msg}\n"
        def _append():
            try:
                self.log_text.insert("end", line)
                self.log_text.see("end")
                # prevent huge log
                if int(self.log_text.index('end-1c').split('.')[0]) > 900:
                    self.log_text.delete('1.0', '200.0')
            except Exception:
                pass
        if hasattr(self, "log_text"):
            self.root.after(0, _append)

    def copy_log(self):
        text = self.log_text.get("1.0", "end-1c")
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.add_log("Journal copié")

    def save_log(self):
        path = filedialog.asksaveasfilename(defaultextension=".txt", filetypes=[("Text", "*.txt")])
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.log_text.get("1.0", "end-1c"))
            self.add_log(f"Journal enregistré : {path}")

    def clear_log(self):
        self.log_text.delete("1.0", "end")

    def check_deps(self):
        errs = []
        if get_gamepad is None:
            errs.append(f"inputs manquant : {INPUTS_IMPORT_ERROR}")
        if pyautogui is None:
            errs.append(f"pyautogui manquant : {PYAUTOGUI_IMPORT_ERROR}")
        if errs:
            self.status_var.set("Dépendances manquantes")
            messagebox.showerror("Dépendances", "Installe : py -3.12 -m pip install inputs pyautogui\n\n" + "\n".join(errs))
        else:
            self.status_var.set("Dépendances OK")

    def start_reader(self):
        if get_gamepad is None:
            return
        self.reader_thread = threading.Thread(target=self.reader_loop, daemon=True)
        self.reader_thread.start()
        self.add_log("LECTURE MANETTE : thread démarré")

    def reader_loop(self):
        while self.running:
            try:
                events = get_gamepad()
                for ev in events:
                    if ev.ev_type in ("Absolute", "Key"):
                        self.event_q.put((ev.ev_type, ev.code, ev.state))
            except Exception as exc:
                self.event_q.put(("ERROR", "reader", repr(exc)))
                time.sleep(0.5)

    def normalize_axis(self, raw, inv=False):
        # expected -32768..32767, threshold uses raw units
        dz = int(self.deadzone_var.get())
        if abs(raw) <= dz:
            return 0.0
        val = raw / 32767.0 if raw >= 0 else raw / 32768.0
        val = clamp(val, -1.0, 1.0)
        if inv:
            val = -val
        return val

    def speed_curve(self, val, min_v, max_v):
        if val == 0:
            return 0.0
        a = abs(val)
        # expo-ish curve: small movement precise, full tilt fast
        speed = float(min_v) + (float(max_v) - float(min_v)) * (a * a)
        return speed * (1 if val > 0 else -1)

    def move_mouse(self, dx, dy, use_clamp=True):
        if not pyautogui:
            return
        dx_i = int(round(dx))
        dy_i = int(round(dy))
        if dx_i == 0 and dy_i == 0:
            return
        try:
            if use_clamp and self.clamp_screen_var.get():
                x, y = pyautogui.position()
                w, h = screen_size()
                nx = clamp(x + dx_i, 0, w - 1)
                ny = clamp(y + dy_i, 0, h - 1)
                pyautogui.moveTo(nx, ny, duration=0)
            else:
                pyautogui.moveRel(dx_i, dy_i, duration=0)
        except Exception as exc:
            self.add_log(f"OUT move ERROR {exc!r}")

    def do_catchup(self):
        if self.catch_dx or self.catch_dy:
            self.add_log(f"CATCHUP dx={-self.catch_dx} dy={-self.catch_dy}")
            self.move_mouse(-self.catch_dx, -self.catch_dy, use_clamp=True)
            self.catch_dx = 0
            self.catch_dy = 0

    def on_actions_toggle(self):
        if not self.actions_enabled.get():
            self.output.release_all()
            self.status_var.set("Actions OFF")
        else:
            self.status_var.set("Actions ON")

    def pump_events(self):
        changed = False
        count = 0
        while True:
            try:
                ev_type, code, value = self.event_q.get_nowait()
            except queue.Empty:
                break
            count += 1
            if ev_type == "ERROR":
                self.add_log(f"INPUT ERROR {value}")
                continue
            self.state[code] = value
            changed = True
            if self.raw_log_var.get():
                now = time.time()
                if now - self.last_raw_log > 0.08:
                    self.add_log(f"INPUT {code}={value}")
                    self.last_raw_log = now
            if count > 300:
                break
        return changed

    def handle_toggles(self):
        # Left stick click toggles left speed mode
        cur = self.state.get("BTN_THUMBL", 0)
        prev = self.prev_btn.get("BTN_THUMBL", 0)
        if cur and not prev:
            self.lx_fast_mode = not self.lx_fast_mode
            self.left_mode_var.set("Mode vitesse : rapide" if self.lx_fast_mode else "Mode vitesse : normal")
            self.add_log(f"MODE joy gauche = {'rapide' if self.lx_fast_mode else 'normal'}")

        cur = self.state.get("BTN_THUMBR", 0)
        prev = self.prev_btn.get("BTN_THUMBR", 0)
        if cur and not prev:
            self.rx_fast_mode = not self.rx_fast_mode
            self.right_mode_var.set("Mode vitesse : rapide" if self.rx_fast_mode else "Mode vitesse : normal")
            self.add_log(f"MODE joy droit = {'rapide' if self.rx_fast_mode else 'normal'}")

        # Manual catchup on Y press if option enabled
        cur = self.state.get("BTN_NORTH", 0)
        prev = self.prev_btn.get("BTN_NORTH", 0)
        if self.y_manual_catchup.get() and cur and not prev:
            self.do_catchup()

        # Keep copy for next edge detection
        for k in ("BTN_THUMBL", "BTN_THUMBR", "BTN_NORTH"):
            self.prev_btn[k] = self.state.get(k, 0)

    def handle_buttons(self):
        # X/B as hold
        self.output.set_left(bool(self.state.get("BTN_WEST", 0)))
        self.output.set_right(bool(self.state.get("BTN_EAST", 0)))

    def handle_left_joy(self):
        x = self.normalize_axis(self.state.get("ABS_X", 0), self.lx_inv_x.get())
        y = self.normalize_axis(self.state.get("ABS_Y", 0), self.lx_inv_y.get())
        moving = (x != 0.0 or y != 0.0)
        if moving:
            if self.lx_fast_mode:
                mn, mx = self.lx_fast_min.get(), self.lx_fast_max.get()
            else:
                mn, mx = self.lx_min.get(), self.lx_max.get()
            dx = self.speed_curve(x, mn, mx)
            dy = self.speed_curve(y, mn, mx)
            self.output.set_shift(True)
            self.output.set_middle(True)
            self.move_mouse(dx, dy, use_clamp=True)
            self.catch_dx += int(round(dx))
            self.catch_dy += int(round(dy))
        else:
            if self.left_was_moving:
                self.output.set_middle(False)
                self.output.set_shift(False)
                if self.lx_auto_catchup.get():
                    self.do_catchup()
        self.left_was_moving = moving
        return x, y

    def handle_right_joy(self):
        x = self.normalize_axis(self.state.get("ABS_RX", 0), self.rx_inv_x.get())
        y = self.normalize_axis(self.state.get("ABS_RY", 0), self.rx_inv_y.get())
        if x != 0.0 or y != 0.0:
            if self.rx_fast_mode:
                mn, mx = self.rx_fast_min.get(), self.rx_fast_max.get()
            else:
                mn, mx = self.rx_min.get(), self.rx_max.get()
            dx = self.speed_curve(x, mn, mx)
            dy = self.speed_curve(y, mn, mx)
            self.move_mouse(dx, dy, use_clamp=True)
        return x, y

    def handle_dpad(self):
        x_raw = self.state.get("ABS_HAT0X", 0)
        y_raw = self.state.get("ABS_HAT0Y", 0)
        x = -x_raw if self.dpad_inv_x.get() else x_raw
        y = -y_raw if self.dpad_inv_y.get() else y_raw
        moving = x != 0 or y != 0
        if moving:
            self.output.set_shift(False)
            self.output.set_middle(True)
            sp = self.dpad_speed.get()
            self.move_mouse(x * sp, y * sp, use_clamp=True)
        else:
            if self.dpad_was_moving and not self.left_was_moving:
                self.output.set_middle(False)
        self.dpad_was_moving = moving

    def handle_triggers(self):
        now = time.time()
        repeat = max(0.001, self.lt_rt_repeat.get() / 1000.0)
        if now - self.last_scroll < repeat:
            return
        lt = self.state.get("ABS_Z", 0)
        rt = self.state.get("ABS_RZ", 0)
        th = self.lt_rt_threshold.get()
        direction = 0
        if lt >= th and rt < th:
            direction = -1
        elif rt >= th and lt < th:
            direction = 1
        elif lt >= th and rt >= th:
            direction = 1 if rt >= lt else -1
        if direction == 0:
            return
        if self.zoom_invert.get():
            direction = -direction
        step = int(self.scroll_step.get()) * direction
        try:
            pyautogui.scroll(step)
            self.last_scroll = now
        except Exception as exc:
            self.add_log(f"OUT scroll ERROR {exc!r}")

    def tick(self):
        try:
            self.pump_events()
            self.raw_var.set(
                f"RAW LX={self.state.get('ABS_X',0)} LY={self.state.get('ABS_Y',0)} | "
                f"RX={self.state.get('ABS_RX',0)} RY={self.state.get('ABS_RY',0)} | "
                f"LT={self.state.get('ABS_Z',0)} RT={self.state.get('ABS_RZ',0)} | "
                f"HAT={self.state.get('ABS_HAT0X',0)},{self.state.get('ABS_HAT0Y',0)}"
            )
            if self.actions_enabled.get() and self.profile_var.get() == "FUSION":
                self.handle_toggles()
                self.handle_buttons()
                self.handle_left_joy()
                self.handle_right_joy()
                self.handle_dpad()
                self.handle_triggers()
                self.status_var.set("Actions ON")
            else:
                self.output.release_all()
                self.status_var.set("Actions OFF")
        except Exception as exc:
            self.add_log(f"ENGINE ERROR {exc!r}")
            self.output.release_all()
        self.root.after(15, self.tick)

    def on_close(self):
        self.running = False
        self.output.release_all()
        self.single.release()
        self.root.destroy()


def main():
    if sys.platform != "win32":
        print("Ce programme est prévu pour Windows.")
    root = tk.Tk()
    try:
        # keep within typical screen height
        sw = root.winfo_screenwidth()
        sh = root.winfo_screenheight()
        root.geometry(f"940x{min(620, max(480, sh-120))}+40+40")
    except Exception:
        pass
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
