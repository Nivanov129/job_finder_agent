"""Smoke-тест: пакет импортируется и pytest собирает ≥1 тест."""

import job_agent


def test_package_importable():
    assert job_agent.__version__ == "0.1.0"
