import os
import json
from pathlib import Path

# ------- Important paths ------- #
HERE = os.path.dirname(os.path.abspath(__file__))
GEN_DATA = os.path.join(HERE,"Generator/Data")
GEN_EDT = os.path.join(HERE, "Generator/EDT")
PER_DATA = os.path.join(HERE, "Perturbations/Data")
PER_EDT = os.path.join(HERE,"Perturbations/edt")

# ------- Table de conversion slot/heure ------- #
# SLOT_TABLE = ["08h00", "09h30", "11h00", "12h15", "13h00", "14h00", "15h30", "17h00"] #Table des créneaux horaires (pour HTML et scoring uniquement)
SLOT_TABLE = ["08h00", "09h30", "11h00", "12h15", "13h45", "15h15", "16h45", "18h15"]  #Table qui résout le problème des durées trop courtes pour certains slots

# ------- Helpers ------- #
def _actual_course_id(term_course_id: str):
    """
    Prend un course id créé par le term_solver de Generator et le transforme en le vrai id du cours
    """
    id,_,_ = term_course_id.split("_")
    return int(id)

def to_abs_day(week: int, day: int):
    return week*5 + day

def hm(h: str) -> int:
    """'09h30' → 570  (minutes depuis minuit).
    Robuste : '7h' → 420, '17h3' → 1023, '9h30' → 570.
    """
    parts = h.split("h")
    hh = parts[0]
    mm = parts[1] if len(parts) > 1 and parts[1] else "0"
    if len(mm) == 1:
        mm = mm + "0"   # '17h3' → mm='3' → '30'
    return int(hh) * 60 + int(mm)

def min_to_hm(minutes: int) -> str:
    """570 → '09h30'"""
    return f"{minutes // 60:02d}h{minutes % 60:02d}"

# ------- Fonctions principales ------- #
def get_data(filename: str):
    """
    Charge les données utilisées à la création de l'emploi du temps
    """
    filepath = os.path.join(GEN_DATA,filename)

    if not os.path.isfile(filepath):
        raise FileNotFoundError(f"Fichier de données de création {filepath} introuvable")

    with open(filepath, "r", encoding="utf-8") as file:
        data = json.load(file)

    return data

def get_timetable(filename: str):
    """
    Charge l'edt qui a été créé par le générateur
    """
    filepath = os.path.join(GEN_EDT,filename)

    if not os.path.isfile(filepath):
            raise FileNotFoundError(f"Fichier d'emploi du temps {filepath} introuvable")
    
    with open(filepath, "r", encoding="utf-8") as file:
        edt = json.load(file)

    return edt

def get_specs(filename: str):
    """
    Charge l'edt qui a été créé par le générateur
    """
    filepath = os.path.join(PER_DATA,filename)

    if not os.path.isfile(filepath):
            raise FileNotFoundError(f"Fichier de specs {filepath} introuvable")
    
    with open(filepath, "r", encoding="utf-8") as file:
        specs = json.load(file)

    return specs

def gen_to_perturb(data_filename: str, edt_filename: str, specs_filename: str):
    """
    Crée la liste des item d'emploi du temps qui est compatible avec Perturbations
    """
    data = get_data(data_filename)
    edt = get_timetable(edt_filename)
    specs = get_specs(specs_filename)

    #création de liste des course pour chaque prof (cours qu'il peut enseigner)
    t = {}
    for teacher in data["teachers"]:
        for teach in specs["teachers"]:
            if teacher["id"]==teach["id"]:
                t[teach["id"]] = [c["id"] for c in data["courses"] if any(pos in c["name"].split("_")[0] for pos in teach["possible_classes"])]
                # on compare le nom du cours de specs avec le nom du cours dans data (et non tout nom_type_groupe)


    perturb_ok = []

    for item in edt:
        courseid = _actual_course_id(item["course"]) #course
        groupid = item["group"] #group

        # headcount
        g = [g for g in data["groups"] if g["id"]==groupid]
        if g == []:
            print(f"Incohérence de groupes entre edt et data : {groupid} est introuvable dans data")
            g = [g for g in specs["groups"] if g["id"]==groupid]
            if g == []:
                print(f"Incohérence de groupes entre edt et specs : {groupid} est introuvable dans specs")
                return []
            else:
                headcount = g[0]["headcount"]
        else:
            headcount = g[0]["size"]

        group = {"id": groupid, "headcount": headcount} # group
        teacher = item["teacher"]  #la clé "course" du prof est pour le moment vide
        teacher["courses"] = t.get(teacher["id"], [])
        day = to_abs_day(item["week"],item["day"])

        #heures de début et de fin
        if hm(data["time_grid"]["day_start"]) != hm(SLOT_TABLE[0]):
            print(f"Incohérence de conversion slot/heure : heure de début du jour différente dans {data_filename} et {specs_filename}")
            return []
        slot = item["slot"]
        heure_debut = SLOT_TABLE[slot]
        # heure_fin = min_to_hm(hm(heure_debut)+data["time_grid"]["slot_duration_min"])
        ################
        #! FIXME : Problème de durée entre les débuts de cours possible pour 12h15,13h,14h 
                        #!=> pour le moment on résout en coupant la durée du cours mais c'est pas viable pour la suite
        if slot + 1 < len(SLOT_TABLE):
            heure_fin = min_to_hm(
                min(hm(heure_debut) + data["time_grid"]["slot_duration_min"],
                    hm(SLOT_TABLE[slot + 1]))
            )
        else:
            heure_fin = min_to_hm(hm(heure_debut) + data["time_grid"]["slot_duration_min"])
        #################

        room = item["room"]
        #building
        r = [r for r in data["rooms"] if r["name"]==room]
        if r == []:
            print(f"Incohérence de salles entre edt et data : {room} est introuvable dans {data_filename}")
            r = [r for r in specs["rooms"] if r["name"]==room]
            if r == []:
                print(f"Incohérence de salles entre edt et specs : {room} est introuvable dans {specs_filename}")
                return []
        bat = r[0]["bat"]

        #session_type
        c = [c for c in data["courses"] if c["id"]==courseid]
        if c == []:
            print(f"Incohérence cours entre edt et data : cours id={courseid} introuvable dans {data_filename}")
            return []
        st = st = c[0].get("session_type", c[0]["room_types"][0])

        #Test cours partagé
        it = [it for it in perturb_ok if it["course"]==courseid and it["heure_debut"]==heure_debut and it["room"]==room and it["day"]==day]        
        if it == []:
            perturb_ok.append(
                {
                    "course": courseid,
                    "group": [{"id": groupid,"headcount": headcount}],
                    "teacher": teacher,
                    "day": day,
                    "heure_debut": heure_debut,
                    "heure_fin": heure_fin,
                    "room": room,
                    "building": bat,
                    "session_type": st
                }
            )
        else:
            it[0]["group"].append({"id": groupid,"headcount": headcount})

        #Remplissage liste course pour le prof ???

    return perturb_ok

def create_compatible(data_filename: str, edt_filename: str, specs_filename: str, output_filename: str):
    """
    Extrait les infos des fichiers importants, crée le fichier json utilisable par Perturbations
    """
    l = gen_to_perturb(data_filename, edt_filename,specs_filename)


    if l != []:
        # Création du fichier compatbile perturb
        filepath = os.path.join(PER_EDT,output_filename)
        Path(filepath).touch(exist_ok=True)
        with open(filepath,"w", encoding="utf-8") as file:
            json.dump(l,file,ensure_ascii=False,indent=2)
            print(f"Edt compatible Perturbations sauvegardé : {filepath}")
    else:
        print("Fichier conforme vide, non généré")

        

