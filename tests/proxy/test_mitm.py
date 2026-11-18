from mocks.proxy import mitm


def fake_binary(tmp_path, name="mitmdump"):
    path = tmp_path / name
    path.write_text("#!/bin/sh\n")
    path.chmod(0o755)
    return str(path)


def test_the_env_variable_wins(monkeypatch, tmp_path):
    binary = fake_binary(tmp_path)
    monkeypatch.setenv("MITMDUMP_BIN", binary)
    assert mitm.find_mitmdump() == binary


def test_an_env_variable_that_is_not_a_binary_is_skipped(monkeypatch, tmp_path):
    monkeypatch.setenv("MITMDUMP_BIN", str(tmp_path / "missing"))
    monkeypatch.setattr(mitm, "ROOT", str(tmp_path / "app"))
    monkeypatch.setenv("PATH", str(tmp_path))
    assert mitm.find_mitmdump() is None


def test_the_project_venv_comes_before_path(monkeypatch, tmp_path):
    monkeypatch.delenv("MITMDUMP_BIN", raising=False)
    monkeypatch.setattr(mitm, "ROOT", str(tmp_path / "app"))
    (tmp_path / "app" / ".venv" / "bin").mkdir(parents=True)
    local = fake_binary(tmp_path / "app" / ".venv" / "bin")
    other = tmp_path / "other"
    other.mkdir()
    fake_binary(other)
    monkeypatch.setenv("PATH", str(other))
    assert mitm.find_mitmdump() == local


def test_path_is_the_last_resort(monkeypatch, tmp_path):
    monkeypatch.delenv("MITMDUMP_BIN", raising=False)
    monkeypatch.setattr(mitm, "ROOT", str(tmp_path / "app"))
    binary = fake_binary(tmp_path)
    monkeypatch.setenv("PATH", str(tmp_path))
    assert mitm.find_mitmdump() == binary


def test_the_command_line_wires_the_addon_and_the_manager():
    cmd = mitm.command("mitmdump", "127.0.0.1", 9000, "http://127.0.0.1:1234", "/ca")
    assert cmd[:5] == [
        "mitmdump",
        "--listen-host",
        "127.0.0.1",
        "--listen-port",
        "9000",
    ]
    assert mitm.ADDON in cmd and "mock_manager=http://127.0.0.1:1234" in cmd
    assert "confdir=/ca" in cmd
    assert "--ignore-hosts" not in cmd and "ssl_insecure=true" not in cmd


def test_no_mitm_and_insecure_become_mitmdump_options():
    cmd = mitm.command("m", "h", 1, "u", "c", intercept=False, insecure=True)
    assert cmd[cmd.index("--ignore-hosts") + 1] == ".*"
    assert "ssl_insecure=true" in cmd
