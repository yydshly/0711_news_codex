from typer.testing import CliRunner

from newsradar.cli import app


def test_web_command_uses_local_only_defaults(monkeypatch):
    called = {}

    def fake_run(application, *, host, port, log_level):
        called.update(host=host, port=port, log_level=log_level)

    monkeypatch.setattr("uvicorn.run", fake_run)

    result = CliRunner().invoke(app, ["web"])

    assert result.exit_code == 0
    assert called == {"host": "127.0.0.1", "port": 8765, "log_level": "info"}
