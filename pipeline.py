import generate
import subprocess

data_filename = input(">>> Donner le nom du fichier contenant les données pour faire un emploi du temps (pas son path, simplement le nom) : > ")


# data_filename = "data_instance.json"


generate.generate(data_filename)

subprocess.call(["python", "perturb.py"])