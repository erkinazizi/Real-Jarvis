"""Floating animated orb in the screen corner (like ChatGPT voice), drawn by a tiny transparent webview."""
import json
import os
import sys
import threading
import time
from typing import Callable

import webview

import config

HTML = config.BASE_DIR / "ui" / "orb.html"


class _Api:
    """Methods the orb's JavaScript can call."""

    def __init__(self, on_click: Callable[[], None]):
        self._on_click = on_click

    def activate(self) -> None:
        self._on_click()


def _listen_for_dock_click(on_click: Callable[[], None]):
    """Clicking Jarvis's Dock icon while it runs sends macOS a 'reopen' Apple Event to this process
    (the launcher doesn't run again). Treat it like a click on the orb. Returns the handler (keep it alive)."""
    from Foundation import NSAppleEventManager, NSObject
    import objc

    class _Reopen(NSObject):
        @objc.typedSelector(b"v@:@@")
        def handleReopen_withReply_(self, event, reply):
            on_click()

    handler = _Reopen.alloc().init()
    NSAppleEventManager.sharedAppleEventManager().setEventHandler_andSelector_forEventClass_andEventID_(
        handler, b"handleReopen:withReply:",
        int.from_bytes(b"aevt", "big"), int.from_bytes(b"rapp", "big"))   # kCoreEventClass, kAEReopenApplication
    return handler


def _status_menu(items: list[tuple[str, Callable[[], None]]]):
    """Menu-bar icon (top right of the screen) with the given items. Returns objects to keep alive."""
    from AppKit import NSImage, NSMenu, NSMenuItem, NSStatusBar, NSVariableStatusItemLength
    from Foundation import NSObject
    import objc

    class _Target(NSObject):
        @objc.typedSelector(b"v@:@")
        def fire_(self, sender):
            fn = items[sender.tag()][1]
            threading.Thread(target=fn, daemon=True).start()   # never block the UI thread

    target = _Target.alloc().init()
    item = NSStatusBar.systemStatusBar().statusItemWithLength_(NSVariableStatusItemLength)
    icon = config.BASE_DIR / "assets" / "icon.png"
    img = NSImage.alloc().initWithContentsOfFile_(str(icon)) if icon.exists() else None
    if img:
        img.setSize_((18, 18))
        item.button().setImage_(img)
    else:
        item.button().setTitle_("◉")
    item.button().setToolTip_("Jarvis")
    menu = NSMenu.alloc().init()
    for i, (title, _) in enumerate(items):
        if title == "-":
            menu.addItem_(NSMenuItem.separatorItem())
            continue
        mi = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, b"fire:", "")
        mi.setTarget_(target)
        mi.setTag_(i)
        menu.addItem_(mi)
    item.setMenu_(menu)
    return item, target, menu


def restart_now() -> None:
    """Restart Jarvis in place (same process id), e.g. after changing settings."""
    print("🔄 Restarting Jarvis...", flush=True)
    os.execv(sys.executable, [sys.executable, "-u", str(config.BASE_DIR / "main.py")])


class Overlay:
    def __init__(self, on_click: Callable[[], None]):
        size, margin = config.ORB_SIZE, config.ORB_MARGIN
        try:
            screen = webview.screens[0]
            sw, sh = screen.width, screen.height
        except Exception:
            sw, sh = 1470, 956
        x = sw - size - margin if config.ORB_CORNER.endswith("right") else margin
        y = sh - size - margin if config.ORB_CORNER.startswith("bottom") else margin + 30

        kwargs = dict(
            title="Jarvis", url=HTML.as_uri(), js_api=_Api(on_click),
            width=size, height=size, x=x, y=y,
            resizable=False, frameless=True, easy_drag=True, on_top=True,
            transparent=True, background_color="#000000",
        )
        try:
            self.window = webview.create_window(**kwargs, focus=False)   # don't steal focus
        except TypeError:                                                # older pywebview
            self.window = webview.create_window(**kwargs)

        self._on_click = on_click
        self._reopen = None
        self._menu = None
        self.ready = threading.Event()
        self._state = "hidden"
        self._last_level = 0.0
        self.window.events.loaded += self._on_loaded

    # -- macOS window tweaks (must run on the main thread) --------------------
    def _on_main(self, fn: Callable[[], None]) -> None:
        try:
            from PyObjCTools import AppHelper
            AppHelper.callAfter(fn)
        except Exception:
            pass

    def _native_setup(self) -> None:
        try:
            from AppKit import NSApplication
            NSApplication.sharedApplication().setActivationPolicy_(1)   # no Dock icon
            win = self.window.native
            win.setHasShadow_(False)
            win.setLevel_(25)                        # float above normal windows
            win.setCollectionBehavior_(1 | 256)      # show on every Space + over full-screen apps
            win.setIgnoresMouseEvents_(True)         # hidden at start: clicks pass through
        except Exception as e:
            print(f"[orb] native setup skipped: {e}")
        try:
            self._reopen = _listen_for_dock_click(self._on_click)
        except Exception as e:
            print(f"[orb] Dock click not available: {e}")
        try:
            self._menu = _status_menu([
                ("Talk to Jarvis", self._on_click),
                ("Settings…", self.open_settings),
                ("-", None),
                ("Restart Jarvis", restart_now),
                ("Quit Jarvis", lambda: os._exit(0)),
            ])
        except Exception as e:
            print(f"[orb] menu-bar icon not available: {e}")

    def _set_clickthrough(self, on: bool) -> None:
        def fn():
            try:
                self.window.native.setIgnoresMouseEvents_(on)
            except Exception:
                pass
        self._on_main(fn)

    def _on_loaded(self) -> None:
        self._on_main(self._native_setup)
        self.ready.set()

    # -- public API (thread-safe) ----------------------------------------------
    def _js(self, code: str) -> None:
        if self.ready.is_set():
            try:
                self.window.evaluate_js(code)
            except Exception:
                pass

    def open_settings(self) -> None:
        import settings
        settings.open_window(on_restart=restart_now)

    def set_state(self, state: str) -> None:
        """'hidden' | 'listening' | 'thinking' | 'speaking'"""
        if not config.SHOW_ORB:
            state = "hidden"
        if state == self._state:
            return
        self._state = state
        self._set_clickthrough(state == "hidden")
        self._js(f"setState({json.dumps(state)})")

    def set_level(self, value: float) -> None:
        """Audio loudness 0..1 (mic while listening, voice while speaking). Throttled to ~20 fps."""
        now = time.time()
        if now - self._last_level < 0.05:
            return
        self._last_level = now
        self._js(f"setLevel({min(1.0, max(0.0, value)):.3f})")

    def close(self) -> None:
        try:
            self.window.destroy()
        except Exception:
            pass
