from __future__ import annotations

from typing import Protocol

from PIL import Image

from newsradar.desktop.controller import DesktopController
from newsradar.desktop.icon import create_news_codex_icon


def create_tray_icon_image() -> Image.Image:
    return create_news_codex_icon(64)


class DesktopUi(Protocol):
    def show_window(self, url: str) -> None: ...

    def hide_window(self) -> None: ...

    def stop_tray(self) -> None: ...

    def destroy_window(self) -> None: ...

    def run_loop(self) -> None: ...


class DesktopApplication:
    def __init__(self, controller: DesktopController, ui: DesktopUi) -> None:
        self.controller = controller
        self.ui = ui

    def run(self) -> None:
        self.controller.start_service()
        self.ui.show_window(self.controller.url)
        self.ui.run_loop()

    def on_window_closing(self) -> bool:
        self.ui.hide_window()
        return False

    def show(self) -> None:
        self.ui.show_window(self.controller.url)

    def hide(self) -> None:
        self.ui.hide_window()

    def start_service(self) -> None:
        self.controller.start_service()

    def stop_service(self) -> None:
        self.controller.stop_service()

    def quit(self) -> None:
        status = self.controller.shutdown()
        if status.state == "failed":
            return
        self.ui.stop_tray()
        self.ui.destroy_window()


class PyWebviewTrayUi:
    """Lazy pywebview/pystray adapter used only by `newsradar desktop run`."""

    def __init__(self) -> None:
        self._application: DesktopApplication | None = None
        self._window = None
        self._tray = None
        self._webview = None

    def bind(self, application: DesktopApplication) -> None:
        self._application = application

    def show_window(self, url: str) -> None:
        if self._window is None:
            import webview

            self._webview = webview
            self._window = webview.create_window(
                "News Codex",
                url,
                width=1280,
                height=900,
                min_size=(960, 640),
            )
            self._window.events.closing += self._require_application().on_window_closing
        else:
            self._window.show()

    def hide_window(self) -> None:
        if self._window is not None:
            self._window.hide()

    def stop_tray(self) -> None:
        if self._tray is not None:
            self._tray.stop()

    def destroy_window(self) -> None:
        if self._window is not None:
            self._window.destroy()

    def run_loop(self) -> None:
        if self._window is None or self._webview is None:
            raise RuntimeError("desktop_window_not_initialized")
        self._start_tray()
        self._webview.start(gui="edgechromium")

    def _start_tray(self) -> None:
        from pystray import Icon, Menu, MenuItem

        menu = Menu(
            MenuItem(
                "显示 News Codex",
                lambda _icon, _item: self._require_application().show(),
                default=True,
            ),
            MenuItem("隐藏窗口", lambda _icon, _item: self._require_application().hide()),
            MenuItem("启动服务", lambda _icon, _item: self._require_application().start_service()),
            MenuItem("停止服务", lambda _icon, _item: self._require_application().stop_service()),
            Menu.SEPARATOR,
            MenuItem("退出 News Codex", lambda _icon, _item: self._require_application().quit()),
        )
        self._tray = Icon("news-codex", create_tray_icon_image(), "News Codex", menu)
        self._tray.run_detached()

    def _require_application(self) -> DesktopApplication:
        if self._application is None:
            raise RuntimeError("desktop_application_not_bound")
        return self._application


def run_desktop(*, port: int = 8767) -> None:
    controller = DesktopController(port=port)
    ui = PyWebviewTrayUi()
    application = DesktopApplication(controller, ui)
    ui.bind(application)
    application.run()
