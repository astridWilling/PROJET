import data_to_gen
import os,json, subprocess

def generate(filename:str):
    """
    Conformise le fichier de données en un fichier d'entrée compatible avecle générateur et par la suite appelle le générateur
    """
    try:
        # ---------------- Création d'un fichier d'entrée compatible avec le générateur ---------------- #
        with open(os.path.join(data_to_gen.GEN_DATA,filename), "r", encoding="utf-8") as d:
            data = json.load(d)
        nb_weeks = data["meta"]["nb_weeks"]
        parts = filename.split(".")
        output_filename = parts[0]+"_gen."+parts[-1]
        data_to_gen.generate_valid_gen_file(filename,output_filename,nb_weeks)

        # ---------------- Génération de l'emploi du temps ---------------- #
        subprocess.call(['python', os.path.join(data_to_gen.HERE,'Generator/main.py')])

    except Exception as e:
        print(f"ERREUR : {e}")
