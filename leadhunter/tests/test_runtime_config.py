"""Тесты оперативных настроек: автосоздание, горячая перезагрузка, валидация."""

from __future__ import annotations

import os

from core.sources import ALL_SOURCES
from core.runtime_config import LlmConfig, RuntimeConfig, RuntimeConfigStore


def test_autocreate_and_defaults(tmp_path) -> None:
    path = tmp_path / "settings.yaml"
    store = RuntimeConfigStore(path, defaults=RuntimeConfig())
    assert path.exists()  # файл создан из дефолтов
    cfg = store.current()
    assert cfg.min_score == 60
    assert cfg.min_budget == 50
    assert set(cfg.enabled_sources) == set(ALL_SOURCES)


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


def test_llm_defaults_to_local_ollama(tmp_path) -> None:
    path = tmp_path / "settings.yaml"
    store = RuntimeConfigStore(path, defaults=RuntimeConfig())
    llm = store.current().llm
    assert llm.provider == "ollama"
    assert llm.model == "llama3.1:8b"
    assert llm.base_url == "http://localhost:11434"
    # Блок llm: попадает и в автосозданный файл.
    assert "llm:" in path.read_text(encoding="utf-8")


def test_llm_block_parsed(tmp_path) -> None:
    path = tmp_path / "settings.yaml"
    path.write_text(
        "llm:\n  provider: ollama\n  model: qwen2.5:7b\n  base_url: http://127.0.0.1:11434/\n",
        encoding="utf-8",
    )
    llm = RuntimeConfigStore(path, defaults=RuntimeConfig()).current().llm
    assert llm.model == "qwen2.5:7b"
    assert llm.base_url == "http://127.0.0.1:11434"  # хвостовой слэш убран


def test_llm_block_invalid_falls_back(tmp_path) -> None:
    path = tmp_path / "settings.yaml"
    path.write_text("llm: not-an-object\n", encoding="utf-8")
    assert RuntimeConfigStore(path, defaults=RuntimeConfig()).current().llm == LlmConfig()


def test_source_enabled_semantics() -> None:
    all_on = RuntimeConfig(enabled_sources=())
    assert all_on.source_enabled("rss") is True  # пусто = все включены
    only_upwork = RuntimeConfig(enabled_sources=("upwork",))
    assert only_upwork.source_enabled("upwork") is True
    assert only_upwork.source_enabled("rss") is False
