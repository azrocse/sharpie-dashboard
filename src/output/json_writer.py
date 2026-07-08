import json
import os
from datetime import datetime



def save_json(data, filename="sharpie.json"):
    """
    Guarda resultados analizados en JSON
    """

    output_path = os.path.join(
        "data",
        "analyzed"
    )


    os.makedirs(
        output_path,
        exist_ok=True
    )


    file_path = os.path.join(
        output_path,
        filename
    )


    with open(
        file_path,
        "w",
        encoding="utf-8"
    ) as file:


        json.dump(
            data,
            file,
            indent=4,
            ensure_ascii=False
        )


    return file_path





def save_history(data):
    """
    Guarda histórico por fecha
    """

    today = datetime.now().strftime(
        "%Y-%m-%d"
    )


    output_path = os.path.join(
        "data",
        "history",
        today
    )


    os.makedirs(
        output_path,
        exist_ok=True
    )


    file_path = os.path.join(
        output_path,
        "sharpie.json"
    )


    with open(
        file_path,
        "w",
        encoding="utf-8"
    ) as file:


        json.dump(
            data,
            file,
            indent=4,
            ensure_ascii=False
        )


    return file_path