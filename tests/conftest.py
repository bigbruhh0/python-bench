"""Общие фикстуры pytest для тестов графического интерфейса."""

import os

import pytest


@pytest.fixture(scope="session")
def qapp():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt5.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])
