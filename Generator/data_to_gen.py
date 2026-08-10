import json
from basics import HERE
import os


def generate_valid_gen_file(filename: str, nb_weeks: int):
    filepath = os.path.join(HERE, filename)

    if not os.path.isfile(filepath):
        raise FileNotFoundError(f"Fichier {filepath} introuvable")

    with open(filepath, "r", encoding="utf-8") as file:
        data = json.load(file)

    for c in data["courses"]:
        rtype = c["room_types"][0]
        c["sessions"] = [rtype] * (c["slots_per_week"] * nb_weeks)

    out_path = os.path.join(HERE, "Data", "instance_gen.json")
    with open(out_path, "w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)

    print(f"OK : instance_gen.json généré ({len(data['courses'])} cours, {nb_weeks} semaines)")


generate_valid_gen_file("Data/data_instance.json",15)