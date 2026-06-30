# HyprWin — Windows 11 Tiling Window Manager

## What It Is

A tiling window manager for Windows 11 that shares the Hyprland config format (`hyprland.conf`). Written in pure Python using `ctypes` for Win32 API calls — no extra dependencies.

## Project Structure

```
hyprwin/
├── main.py              # Entry point: CLI args, message loop, signal handling
├── config.py            # Hyprland config parser ($vars, sections, binds, windowrules)
├── layouts.py           # Tiling algorithms: dwindle (master-stack), rows, columns
├── wm.py                # Windows WM core: ctypes Win32 API, event hooks, hotkeys
├── hyprland.conf        # Example config (compatible with Linux Hyprland)
└── memory/
    └── CONTEXT.md       # This file — project memory for cross-machine pickup
```

## Architecture

### config.py
- Parses `hyprland.conf` (same file you use on Linux)
- Supports: `$variables`, `general { }`, `decoration { }`, `input { }`, `bind`, `windowrule`/`windowrulev2`, `exec-once`, `monitor`, `workspace`
- `resolve_modmask()` converts SUPER/ALT/CTRL/SHIFT to Windows MOD_* flags
- `resolve_vk()` converts key names (RETURN, LEFT, F1, etc.) to Windows virtual key codes
- Stores parsed config in `HyprlandConfig` object: `.binds[]`, `.windowrules[]`, `.general{}`, `.variables{}`, `.workspace_count`, etc.

### layouts.py
- `apply_layout(name, count, area, gaps_in, gaps_out, master_factor) -> List[(x,y,w,h)]`
- Three layouts:
  - **dwindle**: Master on left (55%), stack on right — master-stack layout
  - **rows**: Equal horizontal rows
  - **columns**: Equal vertical columns
- All layouts subtract `gaps_out` from the work area edge and `gaps_in` between windows

### wm.py
Core class: `HyprWinWM(config)`

**Window tracking:**
- `SetWinEventHook` with `EVENT_OBJECT_CREATE`, `EVENT_OBJECT_DESTROY`, `EVENT_SYSTEM_FOREGROUND`
- Callback: `_win_event_proc()` — adds/removes windows and re-tiles
- `_enumerate_existing_windows()` via `EnumWindows` on startup
- `_is_window_managed(hwnd)` — filters out invisible windows, tool windows, shell classes (Taskbar, Progman, etc.), child windows, windows without title bar

**Workspaces:**
- Dict `self.workspaces[ws_num] -> Set[hwnd]`
- `switch_workspace(n)` — hides windows on old workspace with `ShowWindow(SW_HIDE)`, shows on new with `ShowWindow(SW_SHOW)`
- `move_window_to_workspace(hwnd, ws)` — moves window between workspaces
- Default 5 workspaces (configurable)

**Tiling:**
- `_arrange(workspace)` — collects tileable windows (non-floating, non-fullscreen), calls `apply_layout`, then `MoveWindow` on each
- Floating windows get `HWND_TOPMOST` to stay on top
- Fullscreen window gets the entire work area
- Re-triggers on window add/remove, workspace switch, layout change, resize

**Floating & Rules:**
- `_match_windowrule(win)` — checks window rules with regex matching on `class:` or `title:` selectors
- `toggle_floating(hwnd)` — adds/removes from `self.floating_windows` set
- `toggle_fullscreen(hwnd)` — sets/clears `self.fullscreen_window`

**Hotkeys:**
- `register_keybinds()` — calls `RegisterHotKey` for each parsed bind
- `handle_hotkey(hotkey_id)` — looks up dispatcher and calls `_dispatch()`
- Supported dispatchers: `exec`, `killactive`, `workspace`, `movetoworkspace`, `togglefloating`, `fullscreen`, `cyclenext`/`layoutmsg`, `movefocus`, `movewindow`, `resizeactive`, `splitratio`

**Message loop:**
- `run_message_loop()` — `GetMessageW` loop dispatching `WM_HOTKEY` messages

### Windows API surface (via ctypes)

| Function | Purpose |
|----------|---------|
| `SetWinEventHook` | Window creation/destruction/focus notifications |
| `UnhookWinEvent` | Cleanup |
| `EnumWindows` | Enumerate existing windows on startup |
| `GetWindowTextW` | Read window title |
| `GetClassNameW` | Read window class name |
| `GetWindowRect` | Get window position/size |
| `MoveWindow` | Position/resize tiled windows |
| `SetWindowPos` | Z-order management (TOPMOST for floats) |
| `ShowWindow` | Show/hide for workspace switching |
| `GetForegroundWindow` | Get focused window |
| `SetForegroundWindow` | Focus a window |
| `RegisterHotKey` | Global keyboard shortcuts |
| `UnregisterHotKey` | Cleanup |
| `GetMessageW`/`DispatchMessageW` | Windows message loop |
| `GetWindowLongW` | Check window styles (WS_CAPTION, WS_EX_TOOLWINDOW, etc.) |
| `IsWindowVisible` | Visibility check |
| `PostMessageW` | Send WM_CLOSE for kill |
| `SystemParametersInfoW(SPI_GETWORKAREA)` | Get desktop work area |
| `GetParent` | Skip child windows |

## Config Format (Hyprland-compatible)

See `hyprland.conf` for the full example. Key points:
- `$terminal`, `$menu` etc. variables work and get substituted
- `general { gaps_in, gaps_out, layout (dwindle|rows|columns) }`
- `bind = MODMASK, KEY, dispatcher, arg`
- `windowrule = action, selector` (selectors: `class:`, `title:`)
- `exec-once = command` runs on startup
- `workspaces = N` to set count

## Current Limitations / Future Work

1. **Virtual desktops**: Uses `ShowWindow(SW_HIDE/SW_SHOW)` — some apps don't handle this well (system tray icons, media playback). Could use Windows 10+ Virtual Desktop API as alternative.
2. **Borders**: Windows doesn't natively support custom window borders. A border simulation could be added by embedding windows or using `DwmExtendFrameIntoClientArea`.
3. **Animations**: None. Hyprland's smooth animations are not possible through Win32 API alone.
4. **Multi-monitor**: `_update_work_area()` uses `SPI_GETWORKAREA` which only returns the primary monitor. Need to use `EnumDisplayMonitors` and per-monitor work areas with corresponding workspaces.
5. **Window swallowing**: Not implemented (Hyprland's `swallow` feature).
6. **Scratchpad**: Not implemented.
7. **Config hot-reload**: Config is parsed once at startup. No `SIGHUP` or keybind-triggered reload.

## How to Run

```powershell
python main.py                    # Run the WM
python main.py --list-keys        # Preview parsed keybinds without starting
python main.py -c myconfig.conf   # Use a different config path
```

Only works on Windows (calls Win32 APIs). Run as a normal user (no admin required).

Config searched in order:
1. `~/.config/hypr/hyprland.conf` (matches Linux path)
2. `~/hyprland.conf`
3. `./hyprland.conf` (project directory)

## Conversation 2026-06-30

- User asked for a Windows 11 tiling WM sharing Hyprland's config format
- Built as pure Python with ctypes (no deps needed)
- Architecture: config parser → layout engine → Win32 WM core → message loop
- All Python files pass py_compile; config parser and layout engine tested successfully
- Example config has 30 keybinds, 7 window rules, 3 layouts
