import generate
import subprocess

# filename = input(">>> Donner le nom du fichier contenant les données pour faire un emploi du temps (pas son path, simplement le nom) : > ")


data_filename = "data_instance.json"
specs_filename = "specs.json"
edt_filename = "test.json"


generate.generate(data_filename)

subprocess.call(["python", "perturb.py"])