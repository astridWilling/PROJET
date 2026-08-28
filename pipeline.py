import generate
import runpy

"""
Génération, Perturbation et résolution.
"""

data_filename = input(">>> Donner le nom du fichier contenant les données pour faire un emploi du temps (pas son path, simplement le nom) : > ")


# data_filename = "data_instance.json"

generate.generate(data_filename) # Génération (fonction generate dans generate.py)

runpy.run_path("perturb.py") # Perturbation (on lance le script dans perturb.py)