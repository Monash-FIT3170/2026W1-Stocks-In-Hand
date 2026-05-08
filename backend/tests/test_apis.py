"""PyTest tests for the APIs in main.py"""
import main

def test_health() -> None:
    """Confirming that the health API returns the "ok" status as expected"""
    assert main.health() == {"status": "ok"}
