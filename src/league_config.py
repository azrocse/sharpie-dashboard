import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent

CONFIG_FILE = ROOT / "config" / "leagues.json"


def load_leagues():

    with open(
        CONFIG_FILE,
        encoding="utf-8"
    ) as file:

        return json.load(file)