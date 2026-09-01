import os

import f1_web_app


def test_repository_dist_build_uses_project_data_root(tmp_path, monkeypatch):
    project = tmp_path / "f1-telemetry-hub"
    dist = project / "dist"
    dist.mkdir(parents=True)
    (project / "F1TelemetryHub.spec").write_text("# build", encoding="utf-8")
    monkeypatch.setattr(f1_web_app.sys, "frozen", True, raising=False)
    monkeypatch.setattr(f1_web_app.sys, "executable", str(dist / "F1TelemetryHub.exe"))
    assert f1_web_app.runtime_data_root() == os.path.abspath(project)


def test_standalone_build_keeps_data_beside_executable(tmp_path, monkeypatch):
    install = tmp_path / "portable"
    install.mkdir()
    monkeypatch.setattr(f1_web_app.sys, "frozen", True, raising=False)
    monkeypatch.setattr(f1_web_app.sys, "executable", str(install / "F1TelemetryHub.exe"))
    assert f1_web_app.runtime_data_root() == os.path.abspath(install)
