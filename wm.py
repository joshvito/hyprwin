import ctypes
import ctypes.wintypes
import re
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Set, Tuple
from config import HyprlandConfig, Bind, WindowRule
from layouts import apply_layout, Rect

# --- Windows constants ---
SW_HIDE = 0
SW_SHOWNORMAL = 1
SW_SHOWMINIMIZED = 2
SW_SHOWMAXIMIZED = 3
SW_SHOWNOACTIVATE = 4
SW_SHOW = 5
SW_MINIMIZE = 6
SW_RESTORE = 9
SW_SHOWDEFAULT = 10

HWND_BOTTOM = 1
HWND_TOP = 0
HWND_TOPMOST = -1
HWND_NOTOPMOST = -2

SWP_NOZORDER = 0x0004
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_SHOWWINDOW = 0x0040
SWP_NOACTIVATE = 0x0010
SWP_FRAMECHANGED = 0x0020

GWL_STYLE = -16
GWL_EXSTYLE = -20

WS_CAPTION = 0x00C00000
WS_THICKFRAME = 0x00040000
WS_MINIMIZEBOX = 0x00020000
WS_MAXIMIZEBOX = 0x00010000
WS_SYSMENU = 0x00080000
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_APPWINDOW = 0x00040000
WS_EX_NOACTIVATE = 0x08000000

EVENT_OBJECT_CREATE = 0x8000
EVENT_OBJECT_DESTROY = 0x8001
EVENT_OBJECT_SHOW = 0x8002
EVENT_OBJECT_HIDE = 0x8003
EVENT_OBJECT_LOCATIONCHANGE = 0x800B
EVENT_SYSTEM_FOREGROUND = 0x0003

WINEVENT_OUTOFCONTEXT = 0x0000
WINEVENT_SKIPOWNPROCESS = 0x0002

WM_HOTKEY = 0x0312
WM_DESTROY = 0x0002
WM_QUIT = 0x0012

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000

# --- ctypes setup ---
user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
dwmapi = ctypes.windll.dwmapi

WINEVENTPROC = ctypes.WINFUNCTYPE(
    None,
    ctypes.c_void_p,
    ctypes.c_uint,
    ctypes.c_void_p,
    ctypes.c_long,
    ctypes.c_long,
    ctypes.c_uint,
    ctypes.c_uint,
)

# --- Window info wrapper ---
class WindowInfo:
    def __init__(self, hwnd: int):
        self.hwnd = hwnd
        self._title: Optional[str] = None
        self._class_name: Optional[str] = None
        self._floating: bool = False
        self._fullscreen: bool = False
        self._workspace: int = 1
        self._prev_rect: Optional[Rect] = None

    @property
    def title(self) -> str:
        if self._title is None:
            self._title = _get_window_text(self.hwnd)
        return self._title

    @property
    def class_name(self) -> str:
        if self._class_name is None:
            self._class_name = _get_class_name(self.hwnd)
        return self._class_name

    def invalidate(self):
        self._title = None
        self._class_name = None

    def __repr__(self):
        return f"WindowInfo({self.hwnd:#x}, '{self._title}', '{self._class_name}')"

    def __hash__(self):
        return hash(self.hwnd)

    def __eq__(self, other):
        if isinstance(other, WindowInfo):
            return self.hwnd == other.hwnd
        return NotImplemented


def _get_window_text(hwnd: int) -> str:
    length = user32.GetWindowTextLengthW(hwnd) + 1
    buf = ctypes.create_unicode_buffer(length)
    user32.GetWindowTextW(hwnd, buf, length)
    return buf.value or ""


def _get_class_name(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value or ""


def _get_window_rect(hwnd: int) -> Rect:
    rect = ctypes.wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return (rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top)


def _is_window_managed(hwnd: int) -> bool:
    if not user32.IsWindowVisible(hwnd):
        return False
    if not _get_window_text(hwnd):
        return False
    ex_style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    if ex_style & WS_EX_TOOLWINDOW and not (ex_style & WS_EX_APPWINDOW):
        return False
    style = user32.GetWindowLongW(hwnd, GWL_STYLE)
    has_caption = style & WS_CAPTION
    has_thickframe = style & WS_THICKFRAME
    if not (has_caption or has_thickframe):
        return False
    cls = _get_class_name(hwnd)
    skip_classes = {
        "Windows.UI.Core.CoreWindow",
        "ApplicationFrameWindow",
        "Windows.UI.CompositionDesktopWindow",
        "Shell_TrayWnd",
        "Shell_SecondaryTrayWnd",
        "Progman",
        "WorkerW",
        "MultitaskingViewFrame",
        "TaskManagerWindow",
        "WindowsShellExperienceHost",
        "Xaml_Window",
        "SysListView32",
        "#32768",
        "#32770",
    }
    if cls in skip_classes:
        return False
    parent = user32.GetParent(hwnd)
    if parent and parent != 0:
        return False
    return True


class HyprWinWM:
    def __init__(self, config: HyprlandConfig):
        self.config = config
        self.windows: Dict[int, WindowInfo] = {}
        self.workspaces: Dict[int, Set[int]] = {i + 1: set() for i in range(max(config.workspace_count, 5))}
        self.current_workspace: int = 1
        self.floating_windows: Set[int] = set()
        self.fullscreen_window: Optional[int] = None
        self.layout_name: str = config.general.get("layout", "dwindle")
        self.master_factor: float = 0.55
        self._hooks: List[ctypes.c_void_p] = []
        self._running = False
        self._hotkey_ids: Dict[int, Tuple[str, str, str, str]] = {}
        self._next_hotkey_id = 1
        self._callback_refs: List[Any] = []
        self._lock = threading.Lock()

        self._work_area: Rect = (0, 0, 1920, 1080)
        self._update_work_area()

    def _update_work_area(self):
        rect = ctypes.wintypes.RECT()
        user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0)
        self._work_area = (rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top)

    def _match_windowrule(self, win: WindowInfo) -> Optional[str]:
        for rule in self.config.windowrules:
            selector = rule.selector
            action = rule.action
            if selector.startswith("class:"):
                pattern = selector[len("class:"):].strip()
                try:
                    if re.search(pattern, win.class_name, re.IGNORECASE):
                        return action
                except re.error:
                    pass
            elif selector.startswith("title:"):
                pattern = selector[len("title:"):].strip()
                try:
                    if re.search(pattern, win.title, re.IGNORECASE):
                        return action
                except re.error:
                    pass
        return None

    def add_window(self, hwnd: int):
        if hwnd in self.windows:
            return
        if not _is_window_managed(hwnd):
            return

        win = WindowInfo(hwnd)
        rule_action = self._match_windowrule(win)
        if rule_action == "float":
            self.floating_windows.add(hwnd)
        elif rule_action == "tile" and hwnd in self.floating_windows:
            self.floating_windows.discard(hwnd)

        self.windows[hwnd] = win
        ws = self.current_workspace
        self.workspaces[ws].add(hwnd)
        win._workspace = ws

        print(f"[wm] Added window {hwnd:#x} '{win.title}' [{win.class_name}] "
              f"{'float' if hwnd in self.floating_windows else 'tile'} "
              f"ws={ws}")
        self._arrange(self.current_workspace)

    def remove_window(self, hwnd: int):
        win = self.windows.pop(hwnd, None)
        if win is None:
            return
        self.floating_windows.discard(hwnd)
        if self.fullscreen_window == hwnd:
            self.fullscreen_window = None
        for ws in self.workspaces.values():
            ws.discard(hwnd)
        print(f"[wm] Removed window {hwnd:#x}")
        self._arrange(self.current_workspace)

    def _get_managed_windows(self, workspace: int) -> List[int]:
        tileable = []
        for hwnd in self.workspaces.get(workspace, set()):
            if hwnd not in self.windows:
                continue
            if self.fullscreen_window == hwnd:
                return [hwnd]
            if hwnd not in self.floating_windows:
                tileable.append(hwnd)
        return tileable

    def _arrange(self, workspace: int):
        tileable = self._get_managed_windows(workspace)
        n = len(tileable)
        if n == 0:
            return

        gaps_in = self.config.general.get("gaps_in", 5)
        gaps_out = self.config.general.get("gaps_out", 10)

        rects = apply_layout(
            self.layout_name, n, self._work_area,
            gaps_in=gaps_in, gaps_out=gaps_out,
            master_factor=self.master_factor,
        )

        with self._lock:
            for hwnd, rect in zip(tileable, rects):
                x, y, w, h = rect
                user32.MoveWindow(hwnd, x, y, w, h, True)
                user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                                    SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE)

            for fw in self.floating_windows:
                if fw in self.workspaces.get(workspace, set()):
                    user32.SetWindowPos(fw, HWND_TOPMOST, 0, 0, 0, 0,
                                        SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE)

    def move_window_to_workspace(self, hwnd: int, target_ws: int):
        if hwnd not in self.windows:
            return
        win = self.windows[hwnd]
        old_ws = win._workspace
        if old_ws == target_ws:
            return
        if old_ws in self.workspaces:
            self.workspaces[old_ws].discard(hwnd)
        self.workspaces[target_ws].add(hwnd)
        win._workspace = target_ws
        if old_ws == self.current_workspace:
            user32.ShowWindow(hwnd, SW_HIDE)
        if target_ws == self.current_workspace:
            user32.ShowWindow(hwnd, SW_SHOW)
        self._arrange(old_ws)
        self._arrange(self.current_workspace)

    def switch_workspace(self, ws: int):
        if ws == self.current_workspace:
            return
        if ws not in self.workspaces:
            return

        old_ws = self.current_workspace
        self.current_workspace = ws

        for hwnd in self.workspaces.get(old_ws, set()):
            if hwnd in self.windows:
                user32.ShowWindow(hwnd, SW_HIDE)

        for hwnd in self.workspaces.get(ws, set()):
            if hwnd in self.windows:
                user32.ShowWindow(hwnd, SW_SHOW)
                user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                                    SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE)

        self._arrange(ws)

        for hwnd in self.workspaces[ws]:
            if hwnd in self.windows:
                user32.SetForegroundWindow(hwnd)
                break

        print(f"[wm] Switched to workspace {ws}")

    def toggle_floating(self, hwnd: Optional[int] = None):
        if hwnd is None:
            hwnd = user32.GetForegroundWindow()
        if hwnd not in self.windows:
            return
        if hwnd in self.floating_windows:
            self.floating_windows.discard(hwnd)
            self._arrange(self.current_workspace)
        else:
            self.floating_windows.add(hwnd)

    def toggle_fullscreen(self, hwnd: Optional[int] = None):
        if hwnd is None:
            hwnd = user32.GetForegroundWindow()
        if hwnd not in self.windows:
            return
        if self.fullscreen_window == hwnd:
            self.fullscreen_window = None
            self._arrange(self.current_workspace)
        else:
            self.fullscreen_window = hwnd
            x, y, w, h = self._work_area
            user32.MoveWindow(hwnd, x, y, w, h, True)
            user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                                SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE)

    def kill_active(self):
        hwnd = user32.GetForegroundWindow()
        if hwnd in self.windows:
            user32.PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE

    def focus_window(self, direction: str):
        tileable = self._get_managed_windows(self.current_workspace)
        if not tileable:
            return
        current = user32.GetForegroundWindow()
        if current in tileable:
            idx = tileable.index(current)
            if direction == "up" or direction == "left":
                idx = (idx - 1) % len(tileable)
            elif direction == "down" or direction == "right":
                idx = (idx + 1) % len(tileable)
            target = tileable[idx]
        else:
            target = tileable[0]
        user32.SetForegroundWindow(target)

    def cycle_layout(self):
        layouts = ["dwindle", "rows", "columns"]
        try:
            idx = layouts.index(self.layout_name)
            self.layout_name = layouts[(idx + 1) % len(layouts)]
        except ValueError:
            self.layout_name = "dwindle"
        self._arrange(self.current_workspace)

    def change_master_factor(self, delta: float):
        self.master_factor = max(0.2, min(0.8, self.master_factor + delta))
        self._arrange(self.current_workspace)

    def exec_command(self, cmd: str):
        import subprocess
        try:
            subprocess.Popen(cmd, shell=True)
        except Exception as e:
            print(f"[wm] exec error: {e}")

    def handle_hotkey(self, hotkey_id: int):
        info = self._hotkey_ids.get(hotkey_id)
        if info is None:
            return
        mod_str, key_str, dispatcher, arg = info
        self._dispatch(dispatcher, arg)

    def _dispatch(self, dispatcher: str, arg: str):
        d = dispatcher.lower()
        if d == "exec":
            self.exec_command(arg)
        elif d == "killactive":
            self.kill_active()
        elif d == "workspace":
            try:
                ws = int(arg)
                self.switch_workspace(ws)
            except ValueError:
                pass
        elif d == "movetoworkspace":
            try:
                ws = int(arg)
                hwnd = user32.GetForegroundWindow()
                self.move_window_to_workspace(hwnd, ws)
            except ValueError:
                pass
        elif d == "togglefloating":
            self.toggle_floating()
        elif d == "fullscreen":
            self.toggle_fullscreen()
        elif d == "cyclenext" or d == "layoutmsg":
            if "split" in arg.lower() or "next" in arg.lower():
                self.cycle_layout()
            elif "master" in arg.lower() and "factor" in arg.lower():
                try:
                    parts = arg.split()
                    for i, p in enumerate(parts):
                        if p == "master" and i + 1 < len(parts):
                            self.master_factor = float(parts[i + 1])
                            self._arrange(self.current_workspace)
                except (ValueError, IndexError):
                    pass
        elif d == "movefocus":
            self.focus_window(arg)
        elif d == "movewindow":
            self._move_window_in_layout(arg)
        elif d == "resizeactive":
            self._resize_active(arg)
        elif d == "splitratio":
            try:
                val = float(arg)
                ratio = val / 100.0 if val > 1 else val
                self.change_master_factor(ratio - self.master_factor)
            except ValueError:
                pass
        elif d == "exec-once":
            self.exec_command(arg)

    def _move_window_in_layout(self, direction: str):
        hwnd = user32.GetForegroundWindow()
        tileable = self._get_managed_windows(self.current_workspace)
        if hwnd not in tileable or len(tileable) < 2:
            return
        idx = tileable.index(hwnd)
        if direction in ("up", "left") and idx > 0:
            tileable[idx], tileable[idx - 1] = tileable[idx - 1], tileable[idx]
        elif direction in ("down", "right") and idx < len(tileable) - 1:
            tileable[idx], tileable[idx + 1] = tileable[idx + 1], tileable[idx]
        self._arrange(self.current_workspace)

    def _resize_active(self, arg: str):
        parts = arg.split()
        if len(parts) < 2:
            return
        try:
            delta = abs(float(parts[1])) / 100.0
        except ValueError:
            delta = 0.05
        if parts[0].lower() in ("up", "left"):
            self.change_master_factor(-delta)
        else:
            self.change_master_factor(delta)

    def register_keybinds(self):
        for bind in self.config.binds:
            mod_mask = self.config.resolve_modmask(bind.mod)
            vk = self.config.resolve_vk(bind.key)
            if vk == 0:
                continue
            hotkey_id = self._next_hotkey_id
            self._next_hotkey_id += 1
            success = user32.RegisterHotKey(None, hotkey_id, mod_mask, vk)
            if success:
                self._hotkey_ids[hotkey_id] = (bind.mod, bind.key, bind.dispatcher, bind.arg)
                print(f"[wm] Registered hotkey: {bind.mod}+{bind.key} -> {bind.dispatcher} {bind.arg}")
            else:
                print(f"[wm] Failed to register hotkey: {bind.mod}+{bind.key}")

    def _win_event_proc(self, h_hook, event, hwnd, id_obj, id_child, dw_thread, dw_time):
        if event == EVENT_OBJECT_CREATE and id_obj == 0 and id_child == 0:
            if hwnd not in self.windows:
                self.add_window(hwnd)
        elif event == EVENT_OBJECT_DESTROY and id_obj == 0 and id_child == 0:
            self.remove_window(hwnd)
        elif event == EVENT_OBJECT_SHOW and id_obj == 0 and id_child == 0:
            with self._lock:
                if hwnd not in self.windows:
                    pass
        elif event == EVENT_SYSTEM_FOREGROUND:
            if hwnd in self.windows and hwnd in self.floating_windows:
                user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                                    SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE)

    def start(self):
        self._running = True
        self.register_keybinds()
        self._setup_hooks()
        self._enumerate_existing_windows()

    def _setup_hooks(self):
        callback = WINEVENTPROC(self._win_event_proc)
        self._callback_refs.append(callback)
        hook1 = user32.SetWinEventHook(
            EVENT_OBJECT_CREATE, EVENT_OBJECT_DESTROY,
            None, callback, 0, 0, WINEVENT_OUTOFCONTEXT,
        )
        hook2 = user32.SetWinEventHook(
            EVENT_SYSTEM_FOREGROUND, EVENT_SYSTEM_FOREGROUND,
            None, callback, 0, 0, WINEVENT_OUTOFCONTEXT,
        )
        if hook1:
            self._hooks.append(hook1)
        if hook2:
            self._hooks.append(hook2)

    def _enumerate_existing_windows(self):
        enum_callback = ctypes.WINFUNCTYPE(
            ctypes.c_bool,
            ctypes.c_void_p,
            ctypes.c_void_p,
        )
        windows_list = []

        def enum_proc(hwnd, _lparam):
            windows_list.append(hwnd)
            return True

        cb = enum_callback(enum_proc)
        user32.EnumWindows(cb, 0)
        for hwnd in windows_list:
            if _is_window_managed(hwnd):
                self.add_window(hwnd)

    def stop(self):
        self._running = False
        for hook in self._hooks:
            user32.UnhookWinEvent(hook)
        self._hooks.clear()
        for hotkey_id in self._hotkey_ids:
            user32.UnregisterHotKey(None, hotkey_id)
        self._hotkey_ids.clear()
        self._callback_refs.clear()

    def run_message_loop(self):
        msg = ctypes.wintypes.MSG()
        while self._running:
            ret = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if ret == 0:
                break
            if msg.message == WM_HOTKEY:
                self.handle_hotkey(msg.wParam)
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
