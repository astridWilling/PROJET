import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
GEN_DATA = os.path.join(HERE,"Generator/Data")


def generate_valid_gen_file(filename: str, output_filename: str, nb_weeks: int=15):
    filepath = os.path.join(GEN_DATA, filename)

    if not os.path.isfile(filepath):
        raise FileNotFoundError(f"Fichier {filepath} introuvable")

    with open(filepath, "r", encoding="utf-8") as file:
        data = json.load(file)

    for c in data["courses"]:
        rtype = c["room_types"][0]
        c["sessions"] = [rtype] * (c["slots_per_week"] * nb_weeks)

    out_path = os.path.join(GEN_DATA, output_filename)
    with open(out_path, "w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)

    print(f"OK : \033[1;94m{out_path}\033[0m généré ({len(data['courses'])} cours, {nb_weeks} semaines)")


# generate_valid_gen_file("data_instance.json","instance_gen.json",15)