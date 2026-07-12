from __future__ import annotations

import signal

from newsradar.runtime import RuntimeSupervisor


class FakeProcess:
    def __init__(self, exit_code: int | None) -> None:
        self.exit_code = exit_code
        self.signal_received: int | None = None
        self.terminate_called = False
        self.wait_called = False

    def poll(self) -> int | None:
        return self.exit_code

    def send_signal(self, signum: int) -> None:
        self.signal_received = signum
        self.exit_code = -signum

    def terminate(self) -> None:
        self.terminate_called = True
        self.exit_code = -signal.SIGTERM

    def wait(self, timeout: float | None = None) -> int:
        self.wait_called = True
        return self.exit_code or 0


def process_factory(*processes: FakeProcess):
    iterator = iter(processes)

    def create(args):
        return next(iterator)

    return create


def test_supervisor_stops_web_when_worker_exits_abnormally() -> None:
    web = FakeProcess(exit_code=None)
    worker = FakeProcess(exit_code=7)

    result = RuntimeSupervisor(process_factory=process_factory(web, worker)).run()

    assert result == 7
    assert web.signal_received == signal.SIGTERM
    assert web.wait_called


def test_supervisor_forwards_interrupt_to_both_children() -> None:
    web = FakeProcess(exit_code=None)
    worker = FakeProcess(exit_code=None)
    supervisor = RuntimeSupervisor(process_factory=process_factory(web, worker))

    supervisor.start()
    supervisor.stop(signal.SIGINT)

    assert web.signal_received == signal.SIGINT
    assert worker.signal_received == signal.SIGINT
