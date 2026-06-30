import os
import sys
import signal
import argparse

from config import HyprlandConfig
from wm import HyprWinWM


def find_config() -> str:
    candidates = [
        os.path.expanduser("~/.config/hypr/hyprland.conf"),
        os.path.expanduser("~/hyprland.conf"),
        os.path.join(os.path.dirname(__file__), "hyprland.conf"),
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    return candidates[-1]


def main():
    parser = argparse.ArgumentParser(description="HyprWin - Windows 11 tiling window manager")
    parser.add_argument("-c", "--config", help="Path to hyprland.conf")
    parser.add_argument("--list-keys", action="store_true", help="List all registered hotkeys")
    args = parser.parse_args()

    config_path = args.config or find_config()
    print(f"[hyprwin] Loading config: {config_path}")

    config = HyprlandConfig()
    config.parse(config_path)

    if args.list_keys:
        print("\nParsed keybinds:")
        for b in config.binds:
            print(f"  {b.mod} + {b.key:10s} -> {b.dispatcher:20s} {b.arg}")
        print(f"\nWindow rules ({len(config.windowrules)}):")
        for r in config.windowrules:
            print(f"  {r.action:10s} : {r.selector}")
        print(f"\nLayout: {config.general.get('layout', 'dwindle')}")
        print(f"Workspaces: {config.workspace_count}")
        print(f"Gaps in/out: {config.general.get('gaps_in')}/{config.general.get('gaps_out')}")
        return

    wm = HyprWinWM(config)

    def shutdown(signum, frame):
        print("\n[hyprwin] Shutting down...")
        wm.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    print("[hyprwin] Starting HyprWin...")
    print("[hyprwin] Press Ctrl+C in the terminal to quit")
    wm.start()
    wm.run_message_loop()


if __name__ == "__main__":
    main()
