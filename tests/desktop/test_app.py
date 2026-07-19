from __future__ import annotations

from dataclasses import dataclass

from newsradar.desktop.app import DesktopApplication, create_tray_icon_image
from newsradar.desktop.controller import DesktopStatus


@dataclass
class FakeController:
    start_calls: int = 0
    shutdown_calls: int = 0
    url: str = "http://127.0.0.1:8767/daily-reports"
    shutdown_status: DesktopStatus = DesktopStatus("stopped", "已停止")

    def start_service(self) -> DesktopStatus:
        self.start_calls += 1
        return DesktopStatus("running", "已启动")

    def shutdown(self) -> DesktopStatus:
        self.shutdown_calls += 1
        return self.shutdown_status


@dataclass
class FakeUi:
    shown_url: str | None = None
    hidden: bool = False
    tray_stopped: bool = False
    destroyed: bool = False
    ran: bool = False

    def show_window(self, url: str) -> None:
        self.shown_url = url

    def hide_window(self) -> None:
        self.hidden = True

    def stop_tray(self) -> None:
        self.tray_stopped = True

    def destroy_window(self) -> None:
        self.destroyed = True

    def run_loop(self) -> None:
        self.ran = True


def test_window_close_hides_instead_of_stopping_service() -> None:
    controller = FakeController()
    ui = FakeUi()
    app = DesktopApplication(controller, ui)

    keep_open = app.on_window_closing()

    assert keep_open is False
    assert ui.hidden is True
    assert controller.shutdown_calls == 0


def test_explicit_quit_stops_owned_service_and_tray() -> None:
    controller = FakeController()
    ui = FakeUi()
    app = DesktopApplication(controller, ui)

    app.quit()

    assert controller.shutdown_calls == 1
    assert ui.tray_stopped is True
    assert ui.destroyed is True


def test_quit_keeps_desktop_open_when_owned_service_does_not_stop() -> None:
    controller = FakeController(shutdown_status=DesktopStatus("failed", "停止超时"))
    ui = FakeUi()

    DesktopApplication(controller, ui).quit()

    assert controller.shutdown_calls == 1
    assert ui.tray_stopped is False
    assert ui.destroyed is False


def test_run_starts_service_shows_daily_reports_and_enters_ui_loop() -> None:
    controller = FakeController()
    ui = FakeUi()

    DesktopApplication(controller, ui).run()

    assert controller.start_calls == 1
    assert ui.shown_url == controller.url
    assert ui.ran is True


def test_tray_icon_uses_shared_64_pixel_artwork() -> None:
    from newsradar.desktop.icon import create_news_codex_icon

    tray = create_tray_icon_image()

    assert tray.size == (64, 64)
    assert tray.tobytes() == create_news_codex_icon(64).tobytes()
