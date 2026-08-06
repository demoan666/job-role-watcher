"""Loads local backend config (API keys, host/port) from config.json.

config.json is gitignored — never commit real secrets. config.example.json
documents the expected keys; copy it to config.json and fill in real values.
"""

import json
import os

CONFIG_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")
EXAMPLE_PATH = os.path.join(CONFIG_DIR, "config.example.json")


def load_config():
    if not os.path.exists(CONFIG_PATH):
        raise FileNotFoundError(
            f"backend/config.json not found. Copy {EXAMPLE_PATH} to {CONFIG_PATH} "
            "and fill in your own values (never commit this file)."
        )
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)
