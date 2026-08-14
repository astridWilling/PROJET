import os, json
from unittest.mock import patch
import runpy

HERE = os.path.dirname(os.path.abspath(__file__))
GEN_DATA = os.path.join(HERE,"Generator/Data")
GEN_EDT = os.path.join(HERE, "Generator/EDT")
PER_DATA = os.path.join(HERE, "Perturbations/Data")
PER_EDT = os.path.join(HERE,"Perturbations/edt")

path_main = os.path.join(HERE,"pipeline.py")

data_filename = ["data_instance.json"]
specs_filename = ["specs.json"]

parts = data_filename[0].split(".") ; instance = parts[0]+"_gen."+parts[1]
data_path = os.path.join(GEN_DATA,data_filename[0])
gen_path = os.path.join(GEN_DATA,instance)
with open(data_path,'r',encoding='utf-8') as d:
    data = json.load(d)
nb_weeks = data["meta"]["nb_weeks"]

#! ---------------- Generator
edt_raw = "edt_test"
gen = ["Y",
        f"{gen_path}", str(nb_weeks),
        "60","60","8","","2","2","2",
        edt_raw,
        "y"
       ]

#! ---------------- Perturbations
# ------------ Setup ------------ #
psetup = data_filename + specs_filename + [edt_raw+".json"] + [edt_raw+"_perturb.json"]

# ------------ Aujourd'hui ------------ #
ajd = ["13"] # "" pour regarder tout l'edt

# ------------ Types de résolution ------------ #
cascade = ["0","1","y"]
full_solve = ["0","2","y"]
perturbs = [
    "1","T_Tom","15,08h00,19h00 16,08h00,19h00 17,08h00,19h00 18,08h00,19h00 19,08h00,19h00",
    "2","GB42","25,08h00,19h00 26,8h,19h",
    "3","","37,8h,12h30",
    "4","T_Gégé","Elec","","","31,8h,9h30",
    "5","Thermo","1_C","10","48","",
    "6","SI","1_C","12","Esp","1_C","12","y","y",
    "7","Mat2","1_C","28","Amphi102","y",
    "8","Electro","1_C","T_Tom","TD","75","3","0","","",
    "8","Electro","1_C","T_Tom","TD","75","13","0","","",
    "8","Electro","1_C","T_Tom","TD","75","5","0","","GB42",
    "9", "Elec", "1_G", "CM", "7", ""
]

side_eff = data_filename+gen+psetup+ajd+perturbs+full_solve

with patch("builtins.input", side_effect=side_eff):
    runpy.run_path(path_main, run_name="__main__")
