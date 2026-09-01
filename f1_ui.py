"""Windows high-DPI helpers shared by every graphical entry point."""

import os
import sys
import tkinter as tk


def enable_high_dpi():
    """Opt into crisp per-monitor rendering before the first Tk window exists."""
    if os.name != "nt":
        return
    try:
        import ctypes
        # A versioned identity prevents Windows from reusing the taskbar icon
        # cached for the earlier Telemetry Hub interface.
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "PaulPopescu.F1RaceCommand.2026.v3"
        )
    except (AttributeError, OSError):
        pass


_instance_mutex = None


def acquire_single_instance(port=20777):
    """Keep accidental double launches from competing for telemetry and data."""
    global _instance_mutex
    if os.name != "nt":
        return True
    try:
        import ctypes
        mutex_name = f"Local\\PaulPopescu.F1RaceCommand.Telemetry.{int(port)}"
        handle = ctypes.windll.kernel32.CreateMutexW(None, False, mutex_name)
        if not handle:
            return True
        if ctypes.windll.kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
            ctypes.windll.kernel32.CloseHandle(handle)
            return False
        _instance_mutex = handle
    except (AttributeError, OSError, TypeError, ValueError):
        return True
    return True


def release_single_instance():
    """Release the Windows instance guard before a controlled app restart."""
    global _instance_mutex
    if os.name == "nt" and _instance_mutex:
        try:
            import ctypes
            ctypes.windll.kernel32.CloseHandle(_instance_mutex)
        except (AttributeError, OSError):
            pass
    _instance_mutex = None
    try:
        import ctypes
        # PER_MONITOR_AWARE_V2 on current Windows 10/11 builds.
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        return
    except (AttributeError, OSError):
        pass
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return
    except (AttributeError, OSError):
        pass
    try:
        import ctypes
        ctypes.windll.user32.SetProcessDPIAware()
    except (AttributeError, OSError):
        pass


def configure_tk_scaling(root):
    """Match Tk point sizes to the physical DPI of the current display."""
    try:
        dpi = float(root.winfo_fpixels("1i"))
        root.tk.call("tk", "scaling", max(1.0, dpi / 72.0))
    except (ValueError, TypeError, AttributeError):
        pass


def resource_path(relative_path):
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, relative_path)


def apply_app_icon(root):
    """Apply the original Race Command mark to source and packaged windows."""
    ico_path = resource_path(os.path.join("assets", "race_command_icon_v2.ico"))
    if os.name == "nt":
        try:
            root.iconbitmap(default=ico_path)
        except (tk.TclError, OSError):
            pass
    try:
        icon = tk.PhotoImage(file=resource_path(os.path.join(
            "assets", "race_command_icon_v2.png")))
        root.iconphoto(True, icon)
        root._race_command_icon = icon
        return icon
    except (tk.TclError, OSError):
        return None


_native_icon_handles = []


def apply_webview_icon(window):
    """Apply big and small icons to pywebview's native WinForms window."""
    if os.name != "nt" or window is None or window.native is None:
        return False
    try:
        import ctypes
        from ctypes import wintypes

        hwnd = int(window.native.Handle.ToInt64())
        icon_path = resource_path(os.path.join(
            "assets", "race_command_icon_v2.ico"))
        user32 = ctypes.windll.user32
        user32.LoadImageW.argtypes = (
            wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT,
            ctypes.c_int, ctypes.c_int, wintypes.UINT)
        user32.LoadImageW.restype = wintypes.HANDLE
        user32.SendMessageW.argtypes = (
            wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
        user32.SendMessageW.restype = wintypes.LPARAM

        image_icon = 1
        load_from_file = 0x0010
        wm_seticon = 0x0080
        small = user32.LoadImageW(None, icon_path, image_icon, 16, 16, load_from_file)
        large = user32.LoadImageW(None, icon_path, image_icon, 32, 32, load_from_file)
        if not small or not large:
            return False
        user32.SendMessageW(hwnd, wm_seticon, 0, int(small))
        user32.SendMessageW(hwnd, wm_seticon, 1, int(large))
        # Keep the HICON resources alive for the lifetime of the native window.
        _native_icon_handles.extend((small, large))
        return True
    except (AttributeError, OSError, TypeError, ValueError):
        return False
