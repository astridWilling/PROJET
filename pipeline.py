import generate
import runpy

data_filename = input(">>> Donner le nom du fichier contenant les données pour faire un emploi du temps (pas son path, simplement le nom) : > ")


# data_filename = "data_instance.json"

print(f"Début de la génération")
generate.generate(data_filename)
print("Fin de la génération")

print("Début de la perturbation")
runpy.run_path("perturb.py")
print("Fin de la perturbation")