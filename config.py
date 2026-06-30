import re
import os
from typing import Any, Dict, List, Optional, Tuple


class Bind:
    def __init__(self, mod: str, key: str, dispatcher: str, arg: str = ""):
        self.mod = mod.upper()
        self.key = key
        self.dispatcher = dispatcher
        self.arg = arg

    def __repr__(self):
        return f"Bind({self.mod}, {self.key}, {self.dispatcher}, {self.arg})"


class WindowRule:
    def __init__(self, action: str, selector: str):
        self.action = action
        self.selector = selector

    def __repr__(self):
        return f"WindowRule({self.action}, {self.selector})"


class HyprlandConfig:
    MONITOR_MOD = 0x8000  # MOD2 (CAPS)

    MOD_MAP = {
        "SUPER": 0x0100 | 0x0008,  # MOD_WIN
        "ALT": 0x0001,             # MOD_ALT
        "CTRL": 0x0002,            # MOD_CONTROL
        "SHIFT": 0x0004,           # MOD_SHIFT
        "CAPS": 0x8000,            # MOD2
    }

    MOD_MAP_LINUX = {
        "SUPER": 0x0100 | 0x0008,
        "ALT": 0x0001,
        "CTRL": 0x0002,
        "SHIFT": 0x0004,
        "CAPS": 0x8000,
    }

    VK_MAP = {
        "RETURN": 0x0D,
        "SPACE": 0x20,
        "TAB": 0x09,
        "ESCAPE": 0x1B,
        "BACKSPACE": 0x08,
        "DELETE": 0x2E,
        "INSERT": 0x2D,
        "HOME": 0x24,
        "END": 0x23,
        "PAGEUP": 0x21,
        "PAGEDOWN": 0x22,
        "UP": 0x26,
        "DOWN": 0x28,
        "LEFT": 0x25,
        "RIGHT": 0x27,
        "COMMA": 0xBC,
        "PERIOD": 0xBE,
        "SLASH": 0xBF,
        "SEMICOLON": 0xBA,
        "APOSTROPHE": 0xDE,
        "MINUS": 0xBD,
        "EQUAL": 0xBB,
        "BACKSLASH": 0xDC,
        "GRAVE": 0xC0,
        "LSHIFT": 0xA0,
        "RSHIFT": 0xA1,
        "LCTRL": 0xA2,
        "RCTRL": 0xA3,
        "LALT": 0xA4,
        "RALT": 0xA5,
    }

    def __init__(self):
        self.variables: Dict[str, str] = {}
        self.sections: Dict[str, Dict[str, Any]] = {}
        self.binds: List[Bind] = []
        self.windowrules: List[WindowRule] = []
        self.exec_once: List[str] = []
        self._raw_lines: List[str] = []
        self._current_section: Optional[str] = None

        self.general = {
            "gaps_in": 5,
            "gaps_out": 10,
            "border_size": 2,
            "col_active_border": "0x66bb3a",
            "col_inactive_border": "0x494d64",
            "layout": "dwindle",
            "no_cursor_warps": False,
            "resize_on_border": False,
            "extend_border_args": False,
            "hover_icon_on_border": True,
            "allow_tearing": False,
            "main_monitor": "",
        }
        self.decoration = {
            "rounding": 0,
            "active_opacity": 1.0,
            "inactive_opacity": 1.0,
            "fullscreen_opacity": 1.0,
            "blur": False,
            "blur_size": 8,
            "blur_passes": 3,
            "blur_noise": 0.01,
            "blur_brightness": 1.0,
            "blur_contrast": 1.0,
            "blur_vibrancy": 0.169,
            "blur_new_optimizations": True,
            "shadow": True,
            "shadow_range": 4,
            "shadow_render_power": 3,
            "shadow_scale": 0.92,
        }
        self.input = {
            "kb_layout": "us",
            "kb_variant": "",
            "kb_options": "",
            "touchpad": False,
            "numlock_by_default": False,
            "follow_mouse": 1,
            "float_switch_center_focus": True,
            "sensitivity": 0.0,
            "accel_profile": "",
        }
        self.workspace_count = 5
        self.workspace_names: Dict[int, str] = {}
        self.monitors: List[Dict[str, Any]] = []

    def _resolve_vars(self, text: str) -> str:
        def repl(m):
            name = m.group(1)
            return self.variables.get(name, m.group(0))
        return re.sub(r'\$\{?(\w+)\}?', repl, text)

    def parse(self, config_path: str):
        if not os.path.exists(config_path):
            print(f"[config] Warning: {config_path} not found, using defaults")
            return

        with open(config_path, 'r') as f:
            lines = f.readlines()

        i = 0
        while i < len(lines):
            raw = lines[i]
            stripped = raw.split('#')[0].strip()
            i += 1

            if not stripped:
                continue

            if stripped.startswith('$') and '=' in stripped:
                parts = stripped.split('=', 1)
                name = parts[0].strip().lstrip('$')
                val = parts[1].strip()
                self.variables[name] = val
                continue

            if self._current_section is None:
                if stripped == '}':
                    self._current_section = None
                    continue

                brace_idx = stripped.find('{')
                if brace_idx >= 0:
                    section_name = stripped[:brace_idx].strip()
                    rest = stripped[brace_idx+1:].strip()
                    self._current_section = section_name
                    if rest:
                        pass
                    continue

                if stripped.startswith('bind'):
                    self._parse_bind(stripped)
                elif stripped.startswith('windowrule'):
                    self._parse_windowrule(stripped)
                elif stripped.startswith('windowrulev2'):
                    self._parse_windowrule(stripped)
                elif stripped.startswith('exec-once'):
                    val = stripped[len('exec-once'):].strip()
                    self.exec_once.append(self._resolve_vars(val))
                elif stripped.startswith('exec'):
                    val = stripped[len('exec'):].strip()
                    self.exec_once.append(self._resolve_vars(val))
                elif stripped.startswith('monitor'):
                    self._parse_monitor(stripped)
                elif stripped.startswith('workspace'):
                    self._parse_workspace(stripped)
                else:
                    self._parse_general_keyval(stripped)
            else:
                if stripped == '}':
                    self._current_section = None
                    continue
                resolved = self._resolve_vars(stripped)
                if '=' in resolved:
                    k, v = resolved.split('=', 1)
                    k = k.strip()
                    v = v.strip()
                    sec = self._current_section
                    if sec == 'general':
                        self.general[k] = self._parse_val(v)
                    elif sec == 'decoration':
                        self.decoration[k] = self._parse_val(v)
                    elif sec == 'input':
                        self.input[k] = self._parse_val(v)
                    else:
                        if sec not in self.sections:
                            self.sections[sec] = {}
                        self.sections[sec][k] = self._parse_val(v)

    def _parse_val(self, v: str):
        v_lower = v.lower()
        if v_lower == 'true':
            return True
        if v_lower == 'false':
            return False
        try:
            if '.' in v:
                return float(v)
            return int(v)
        except ValueError:
            return v

    def _parse_monitor(self, line: str):
        rest = line[len('monitor'):].strip()
        parts = rest.split(',')
        if not parts:
            return
        mon = {"name": parts[0].strip()}
        if len(parts) > 1:
            res = parts[1].strip()
            if res.lower() in ("prefered", "preferred", "auto"):
                mon["resolution"] = None
            elif 'x' in res:
                w, _, h = res.partition('x')
                mon["width"] = int(w.strip())
                mon["height"] = int(h.strip())
        if len(parts) > 2:
            pos = parts[2].strip()
            if pos.lower() == "auto":
                mon["x"] = 0
                mon["y"] = 0
            elif 'x' in pos:
                x_parts = pos.split('x')
                mon["x"] = int(x_parts[0].strip())
                mon["y"] = int(x_parts[1].strip())
        self.monitors.append(mon)

    def _parse_workspace(self, line: str):
        rest = line[len('workspace'):].strip()
        parts = rest.split(',')
        for part in parts:
            part = part.strip()
            if not part:
                continue
            if part.isdigit():
                num = int(part)
                self.workspace_count = max(self.workspace_count, num)
            elif ':' in part:
                k, v = part.split(':', 1)
                if k.strip() == 'name':
                    num_part = rest.split(',')[0].strip()
                    if num_part.isdigit():
                        self.workspace_names[int(num_part)] = v.strip()

    def _parse_bind(self, line: str):
        rest = line[len('bind'):].strip().lstrip('=')
        if rest.startswith('='):
            rest = rest[1:].strip()
        parts = [p.strip() for p in rest.split(',')]
        if len(parts) < 3:
            return
        mod_str = parts[0].upper()
        key_str = parts[1].upper()
        dispatcher = parts[2]
        arg = ','.join(parts[3:]) if len(parts) > 3 else ""
        arg = self._resolve_vars(arg)
        self.binds.append(Bind(mod_str, key_str, dispatcher, arg))

    def _parse_windowrule(self, line: str):
        key = 'windowrule' if 'windowrule' in line[:14] else 'windowrulev2'
        rest = line[len(key):].strip().lstrip('=')
        if rest.startswith('='):
            rest = rest[1:].strip()
        parts = [p.strip() for p in rest.split(',')]
        if len(parts) < 2:
            return
        action = parts[0].lower()
        selector = ','.join(parts[1:]).strip()
        self.windowrules.append(WindowRule(action, selector))

    def _parse_general_keyval(self, line: str):
        if '=' not in line:
            return
        k, v = line.split('=', 1)
        k = k.strip()
        v = self._resolve_vars(v.strip())
        if k == 'workspaces':
            try:
                self.workspace_count = int(v)
            except ValueError:
                pass

    def resolve_modmask(self, mod_str: str) -> int:
        mask = 0
        for part in mod_str.upper().split():
            if part in self.MOD_MAP:
                mask |= self.MOD_MAP[part]
        return mask

    def resolve_vk(self, key_str: str) -> int:
        key_upper = key_str.upper()
        if key_upper in self.VK_MAP:
            return self.VK_MAP[key_upper]
        if len(key_str) == 1:
            return ord(key_str.upper())
        if key_upper.startswith('0X'):
            return int(key_upper, 16)
        try:
            return int(key_upper)
        except ValueError:
            print(f"[config] Unknown key: {key_str}")
            return 0
