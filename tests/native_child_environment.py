"""Explicit import environment for native children testing sealed launchers."""
import os


def clean_native_environment():
    """Keep the runner environment intact; omit only forbidden child overrides."""
    refused = {'PYTHONPATH', 'PYTHONHOME', 'WEATHER_MARKET_REGISTRY'}
    return {name: value for name, value in os.environ.items() if name.upper() not in refused}
