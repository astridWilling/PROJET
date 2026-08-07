from unittest.mock import patch
import runpy
import os

HERE = os.path.dirname(os.path.abspath(__file__))
path_main = os.path.join(HERE, "main.py")

# ------------ Aujourd'hui ------------ #
ajd = ["13"] # "" pour regarder tout l'edt

# ------------ Types de résolution ------------ #
cascade = ["0","1","y"]
full_solve = ["0","2","y"]

# ------------ Cas normaux et tests limites type 8 ------------ #
params_normal = [
    "1","T_Tom","15,08h00,19h00 16,08h00,19h00 17,08h00,19h00 18,08h00,19h00 19,08h00,19h00",
    "2","GB42","25,08h00,19h00 26,8h,19h",
    "3","","37,8h,12h30",
    "4","T_Gégé","Elec","","","31,8h,9h30",
    "5","Thermo","1_C","10","48","",
    "6","SI","1_C","12","Esp","1_C","12","y","y",
    "7","Mat2","1_C","28","Amphi102","y",
    "8","Electro","1_C","T_Tom","TD","75","3","0","","",
    "8","Electro","1_C","T_Tom","TD","75","13","0","","",
    "8","Electro","1_C","T_Tom","TD","75","5","0","","GB42"
]

# ------------ Cas critiques ------------ #
critic1 = [] #Aucun cas critique pour teacher_absent tout seul

critic2 = ["2","","45,9h20,14h20"]  # Toutes les salles sont indispo sur le créneau donc impossible de replacer les cours

critic3 = [] #? ???????????????????


critic4 = ["4","T_Gégé","Elec","","","31,8h,9h30","1","T_Tom","31,8h,9h30","1","T_Eric","31,8h,9h30","1","T_Chris","31,8h,9h30","1","T_Volta","31,8h,9h30"] # Tous les remplaçants ne sont pas dispo au moment où on a besoin d'eux

critic5 = ["5","Thermo","1_C","10","16","","1","T_Max","16,8h,19h"]  # On cherche à déplacer un cours à un jour où le prof est absent

critic6 = [] # Permutation ne fonctionne pas car 1:pas de place pour l'un des 2 cours ; 2:un prof est absent au créneau demandé ; 3:un prof est deja occupé ; 4:un groupe a le créneau demandé libéré ; 5:un groupe est deja occupé

critic7_1 = ["7","Thermo","1_C","12","Amphi9","y","2","Amphi9","56,8h,19h"]
critic7_2 = ["7","Thermo","1_C","12","Amphi112","y"]
critic7_3 = ["7","Thermo","1_C","12","Gym","y"] # 1:salle demandée pas dispo ; 2:salle demandée occupée ; 3:salle incompatible

critic8 = [] # Ajout ne fonctionne pas car 1:prof absent ; 2:prof occupé ; 3:salle indispo ; 4:salle occupée ; 5:groupe occupé ; 6:groupe a le créneau libre


# ------------ Bug bizarre ------------ #
bug = [
    "1","T_Tom","0,09h30,11h00 1,14h00,15h30",
    "2","Amphi9","",
    "3","","10,09h30,11h00 41,14h00,15h30"
]

# ------------ Test ajd ------------ #
test8 = [
    "8","Electro","1_G","T_Tom","TD","75","0","","",
    "8","Mat2","1_C","T_Euler","TD","75","13","",""
]

with patch("builtins.input", side_effect=ajd+test8+full_solve):
    runpy.run_path(path_main, run_name="__main__")