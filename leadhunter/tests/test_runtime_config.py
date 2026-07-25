"""Тесты оперативных настроек: автосоздание, горячая перезагрузка, валидация."""

from __future__ import annotations

import os

from core.runtime_config import RuntimeConfig, RuntimeConfigStore


def test_autocreate_and_defaults(tmp_path) -> None:
    path = tmp_path / "settings.yaml"
    store = RuntimeConfigStore(path, defaults=RuntimeConfig())
    assert path.exists()  # файл создан из дефолтов
    cfg = store.current()
    assert cfg.min_score == 60
    assert cfg.min_budget == 50
    assert set(cfg.enabled_sources) == {"upwork", "fiverr", "rss"}


def test_reads_existing_values(tmp_path) -> None:
    path = tmp_path / "settings.yaml"
    path.write_text("min_score: 75\nmin_budget: 120\nenabled_sources: [upwork]\n", encoding="utf-8")
    store = RuntimeConfigStore(path, defaults=RuntimeConfig())
    cfg = store.current()
    assert cfg.min_score == 75
    assert cfg.min_budget == 120
    assert cfg.enabled_sources == ("upwork",)


def test_hot_reload_on_change(tmp_path) -> None:
    path = tmp_path / "settings.yaml"
    path.write_text("min_score: 60\n", encoding="utf-8")
    store = RuntimeConfigStore(path, defaults=RuntimeConfig())
    assert store.current().min_score == 60

    # Меняем файл и сдвигаем mtime вперёд, чтобы гарантировать перезагрузку.
    path.write_text("min_score: 88\n", encoding="utf-8")
    future = os.stat(path).st_mtime + 100
    os.utime(path, (future, future))

    assert store.current().min_score == 88


def test_invalid_values_fall_back(tmp_path) -> None:
    path = tmp_path / "settings.yaml"
    path.write_text("min_score: not-a-number\nmin_budget: -5\n", encoding="utf-8")
    store = RuntimeConfigStore(path, defaults=RuntimeConfig())
    cfg = store.current()
    assert cfg.min_score == 60  # мусор → дефолт
    assert cfg.min_budget == 0  # отрицательное зажимается к нижней границе


def test_min_score_clamped(tmp_path) -> None:
    path = tmp_path / "settings.yaml"
    path.write_text("min_score: 500\n", encoding="utf-8")
    store = RuntimeConfigStore(path, defaults=RuntimeConfig())
    assert store.current().min_score == 100


def test_unknown_source_dropped(tmp_path) -> None:
    path = tmp_path / "settings.yaml"
    path.write_text("enabled_sources: [upwork, telegram, rss]\n", encoding="utf-8")
    store = RuntimeConfigStore(path, defaults=RuntimeConfig())
    assert store.current().enabled_sources == ("upwork", "rss")


def test_broken_yaml_keeps_defaults(tmp_path) -> None:
    path = tmp_path / "settings.yaml"
    path.write_text("min_score: [unclosed\n", encoding="utf-8")
    store = RuntimeConfigStore(path, defaults=RuntimeConfig())
    # Битый YAML → предыдущие/дефолтные значения, без падения.
    assert store.current().min_score == 60


def test_source_enabled_semantics() -> None:
    all_on = RuntimeConfig(enabled_sources=())
    assert all_on.source_enabled("rss") is True  # пусто = все включены
    only_upwork = RuntimeConfig(enabled_sources=("upwork",))
    assert only_upwork.source_enabled("upwork") is True
    assert only_upwork.source_enabled("rss") is False
