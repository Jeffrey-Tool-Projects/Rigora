from __future__ import annotations

import json

import pytest

from rigora.system import app_paths, settings


@pytest.fixture
def isolated_settings(tmp_path):
    path = tmp_path / "settings.json"
    settings.configure(path, autosave=False)
    yield path
    settings.cancel_pending_save()
    settings.configure(tmp_path / "unused.json", autosave=False)


def test_settings_round_trip_keeps_nested_pet_extensions(isolated_settings):
    expected = {"scale": 1.25, "integration": {"channel": "test"}}
    settings.user_setting_dict["desktop_pet"] = expected
    settings.user_setting_dict["desktop_pet_extras"] = {"second": {"visible": False}}
    settings.flush()
    settings.configure(isolated_settings, autosave=False)
    assert settings.user_setting_dict["desktop_pet"] == expected
    assert settings.user_setting_dict["desktop_pet_extras"]["second"]["visible"] is False


def test_legacy_import_is_scoped_detached_and_does_not_overwrite(isolated_settings):
    settings.user_setting_dict["puppet_recent_files"] = ["new.puppet"]
    settings.flush()
    settings.configure(isolated_settings, autosave=False)
    legacy = {
        "language": "Japanese", "puppet_recent_files": ["old.puppet"],
        "desktop_pet": {"custom": [1]}, "unrelated_private_setting": "not copied",
    }
    assert settings.import_legacy_settings(legacy)
    legacy["desktop_pet"]["custom"].append(2)
    assert settings.user_setting_dict["puppet_recent_files"] == ["new.puppet"]
    assert settings.user_setting_dict["desktop_pet"] == {"custom": [1]}
    assert "unrelated_private_setting" not in settings.user_setting_dict
    assert not settings.import_legacy_settings({"puppet_new": True})
    assert "puppet_new" not in settings.user_setting_dict


@pytest.mark.parametrize("broken", ["{broken", "[]", "null"])
def test_unreadable_settings_are_preserved_before_replacement(tmp_path, broken):
    path = tmp_path / "settings.json"
    path.write_text(broken, encoding="utf-8")
    settings.configure(path, autosave=False)
    settings.user_setting_dict["language"] = "Japanese"
    settings.flush()
    backups = list(tmp_path.glob("settings.json.unreadable-*"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == broken
    assert json.loads(path.read_text(encoding="utf-8"))["language"] == "Japanese"
    settings.configure(tmp_path / "unused.json", autosave=False)


def test_failed_atomic_write_keeps_existing_settings(isolated_settings, monkeypatch):
    settings.flush()
    original = isolated_settings.read_bytes()
    settings.user_setting_dict["language"] = "Japanese"

    def fail(_path, _text):
        raise OSError("disk full")

    monkeypatch.setattr(settings, "write_text_atomically", fail)
    with pytest.raises(OSError, match="disk full"):
        settings.flush()
    assert isolated_settings.read_bytes() == original


def test_failed_corruption_backup_does_not_overwrite(tmp_path, monkeypatch):
    path = tmp_path / "settings.json"
    path.write_text("invalid", encoding="utf-8")
    settings.configure(path, autosave=False)

    def fail(*_args):
        raise PermissionError("cannot back up")

    monkeypatch.setattr(settings.shutil, "copy2", fail)
    with pytest.raises(PermissionError):
        settings.flush()
    assert path.read_text(encoding="utf-8") == "invalid"
    settings.configure(tmp_path / "unused.json", autosave=False)


def test_reconfigure_invalidates_pending_debounced_write(tmp_path, monkeypatch):
    callbacks = []

    class Timer:
        def __init__(self, _delay, callback, args):
            callbacks.append(lambda: callback(*args))

        def start(self):
            pass

        def cancel(self):
            pass

    monkeypatch.setattr(settings.threading, "Timer", Timer)
    settings.configure(tmp_path / "first.json")
    settings.user_setting_dict["language"] = "Japanese"
    settings.configure(tmp_path / "second.json", autosave=False)
    callbacks[0]()
    assert not (tmp_path / "first.json").exists()
    assert not (tmp_path / "second.json").exists()


def test_data_and_resource_paths_are_separate(tmp_path, monkeypatch):
    monkeypatch.setenv("RIGORA_DATA_DIR", str(tmp_path / "state"))
    monkeypatch.delenv("RIGORA_SETTINGS_PATH", raising=False)
    assert app_paths.app_dir() == tmp_path / "state"
    assert app_paths.user_settings_path() == tmp_path / "state" / "settings.json"
    assert app_paths.embedded_python_dir().is_relative_to(app_paths.app_dir())
    assert app_paths.frozen_site_packages().is_relative_to(app_paths.app_dir())
    assert not app_paths.examples_dir().is_relative_to(app_paths.app_dir())


def test_settings_path_override(tmp_path, monkeypatch):
    monkeypatch.setenv("RIGORA_SETTINGS_PATH", str(tmp_path / "isolated.json"))
    assert app_paths.user_settings_path() == tmp_path / "isolated.json"


def test_frozen_dependency_path_is_added_once(tmp_path, monkeypatch):
    monkeypatch.setenv("RIGORA_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(app_paths, "is_frozen", lambda: True)
    directory = app_paths.frozen_site_packages()
    directory.mkdir(parents=True)
    monkeypatch.setattr(app_paths.sys, "path", list(app_paths.sys.path))
    app_paths.ensure_frozen_site_packages_on_path()
    app_paths.ensure_frozen_site_packages_on_path()
    assert app_paths.sys.path.count(str(directory)) == 1


def test_all_native_languages_keep_feature_key_and_placeholder_parity():
    from rigora.i18n.language_wrapper import LanguageWrapper
    from rigora.i18n.translation_validation import extract_placeholders
    wrapper = LanguageWrapper()
    english = wrapper.choose_language_dict["English"]
    assert "file_filter_puppet" in english
    for code, dictionary in wrapper.choose_language_dict.items():
        assert dictionary.keys() == english.keys(), code
        for key, value in dictionary.items():
            assert extract_placeholders(value) == extract_placeholders(english[key]), (code, key)


def test_filters_follow_current_language():
    from rigora.gui.file_filters import translated_filter
    from rigora.i18n.language_wrapper import language_wrapper
    old = language_wrapper.language
    try:
        language_wrapper.reset_language("Japanese")
        value = translated_filter("file_filter_puppet", "Puppet", ["puppet"])
        assert value == language_wrapper.language_word_dict["file_filter_puppet"] + " (*.puppet)"
    finally:
        language_wrapper.reset_language(old)


def test_install_reservation_is_released_after_failure():
    from rigora.dependencies.installation import resource_reservation
    with resource_reservation("python"), pytest.raises(FileExistsError), resource_reservation("python"):
        pytest.fail("second installer entered")
    with pytest.raises(RuntimeError), resource_reservation("python"):
        raise RuntimeError("failed")
    with resource_reservation("python"):
        pass


def test_installer_cancellation_never_launches_pip(tmp_path, monkeypatch):
    from rigora.dependencies.pip_install_workers import _InstallWorker
    worker = _InstallWorker(["sounddevice"], "python")
    monkeypatch.setattr(worker, "isInterruptionRequested", lambda: True)
    assert worker._install_all(tmp_path / "constraints.txt", []) == (
        False, "Dependency installation cancelled",
    )


def test_job_registry_is_owned_separately_from_host(qapp):
    from rigora.gui.background_jobs import job_registry
    sentinel = object()
    qapp._imervue_jobs = sentinel
    registry = job_registry()
    assert registry is job_registry()
    assert registry is not sentinel
    assert qapp._imervue_jobs is sentinel
    del qapp._imervue_jobs


def test_embedding_can_bind_its_job_registry(qapp, monkeypatch):
    from rigora.gui.background_jobs import JobRegistry, job_registry, set_job_registry
    monkeypatch.setattr(qapp, "_rigora_jobs", None, raising=False)
    registry = JobRegistry(qapp)
    set_job_registry(registry)
    assert job_registry() is registry


def test_rebinding_does_not_discard_retained_results(qapp, monkeypatch):
    from rigora.gui.background_jobs import JobRegistry, set_job_registry
    from rigora.system.job_state import JobState
    registry = JobRegistry(qapp)
    state = JobState(["model"])
    state.record("model", output="render.png")
    state.finish()
    registry.add_completed("Render", state)
    monkeypatch.setattr(qapp, "_rigora_jobs", registry, raising=False)
    with pytest.raises(RuntimeError, match="retains jobs"):
        set_job_registry(JobRegistry(qapp))
    assert len(registry.jobs) == 1


def test_widget_helpers_work_without_showing_a_window(qapp):
    from PySide6.QtWidgets import QPushButton, QWidget, QVBoxLayout
    from rigora.gui.control_tooltips import enable_control_tooltips
    from rigora.gui.panel_scroll import PanelScrollArea
    parent = QWidget()
    layout = QVBoxLayout(parent)
    button = QPushButton("Open character", parent)
    layout.addWidget(button)
    enable_control_tooltips(parent)
    area = PanelScrollArea(QWidget(), parent)
    assert button.toolTip()
    assert not parent.isVisible()
    assert area.parent() is parent
    parent.deleteLater()
