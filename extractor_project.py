from Perturbations.basics import *
from Perturbations.gestion import *
from gen_to_perturb import *
import os,json

def get_variables(specs_filename: str, edt_filename: str, data_filename: str):
    """
    Retourne les listes des objets et variables importantes telles que course_list, deadline_days...
    """
    sfilepath = os.path.join(PER_DATA, specs_filename)
    efilepath = os.path.join(PER_EDT, edt_filename)
    dfilepath = os.path.join(GEN_DATA, data_filename)
    with open(sfilepath, "r", encoding="utf-8") as f:
        specs = json.load(f)
    with open(efilepath,"r", encoding="utf-8") as e:
        edt = json.load(e)
    with open(dfilepath,"r", encoding="utf-8") as d:
        data = json.load(d)

    s_g = specs["groups"]
    s_c = specs["courses"]
    s_t = specs["teachers"]
    s_r = specs["rooms"]
    s_b = specs["buildings"]
    s_d = specs["departments"]
    d_c = data["courses"]
    meta = data["meta"]

    # ---------- Création des objets Group ---------- #
    groups_list = []
    for g in s_g:  # Création des objets
        grp = Group(id=g["id"], headcount=g["headcount"], parent=None, subgroup_ids=g["subgroup_ids"])
        groups_list.append(grp)

    for grp in groups_list:  # Remplissage de la liste des parents
        if grp.subgroup_ids != [] and grp.subgroup_ids is not None:
            g = [g for g in groups_list if g.id in grp.subgroup_ids]
            for sg in g:
                sg._replace(parent=grp.id)

    # ---------- Création des objets Teacher ---------- #
    teachers_list = []
    d = {} #dict pour remplir le course de chaque prof
    for teach in s_t: # Création des objets
        t = Teacher(id=teach["id"],name=teach["name"],courses=[], teacher_type=teach["teacher_type"], max_hours=teach["max_hours"], possible_classes=teach["possible_classes"], dept=teach["dept"])
        d[t.id] = []
        teachers_list.append(t)
    
    for item in edt: # remplissage de la liste des cours donnés par chaque prof
        d[item["teacher"]["id"]].append(item["course"])

    teacher_map = {t.id: t for t in teachers_list}

    # ---------- Création des objets Course ---------- #
    courses_list = []
    deadline_days = {}
    for c in d_c:
        cid =  c["id"]
        cname = c["name"].split("_")[0]
        c_spec = next((s for s in s_c if s["name"]==cname), None)

        cteacher = teacher_map.get(c["teacher"], None)
        group_ids = c_spec["groups"]
        room_types = c_spec["room_types"]
        s_p_w = 0  #On s'en fiche
        session_type = c["name"].split("_")[1]
        ordering_pref = c["ordering_preference"]
        dept = c_spec["dept"]
        pref_build = c_spec.get("preferred_buildings",[])
        courses_list.append(Course(cid, cname, cteacher, group_ids, room_types, s_p_w, session_type, ordering_pref, dept, pref_build))
        deadline_days[cid]=c_spec["exam_day"]

    course_map = {c.id: c for c in courses_list}

    # ---------- Création des objets Department ---------- #
    dept_list = []
    for d in s_d:
        did = d["id"]
        dname = d["name"]
        dteachers = [t.id for t in teachers_list if t.dept==did]
        dcourses = [c.id for c in courses_list if c.dept==did]
        dept_list.append(Department(did, dname, dteachers, dcourses))

    # ---------- Création des objets Room ---------- #
    rooms_list = []
    for r in s_r:
        rooms_list.append(Room(r["name"], r["capacity"], r["room_types"], r["bat"]))

    # ---------- Création des objets Building ---------- #
    buildings_list = []
    for b in s_b:
        drooms = [r.name for r in rooms_list if r.bat==b["id"]]
        buildings_list.append(Building(b["id"], b["name"], drooms, b["dist"]))

    # ---------- Création des variables globales utiles ---------- #
    nb_days = meta["nb_weeks"]*meta["nb_days_per_week"]
    LUNCH_DEBUT_MIN = hm(SLOT_TABLE[meta["lunch_slots"][0]])
    LUNCH_FIN_MIN = hm(SLOT_TABLE[meta["lunch_slots"][-1]+1]) #+1 pour avoir la fin du dernier lunch_slot et non le début
    

    return groups_list, teachers_list, courses_list, dept_list, rooms_list, buildings_list, nb_days, deadline_days, LUNCH_DEBUT_MIN, LUNCH_FIN_MIN

def extraction(specs_filename: str, data_filename: str, edt_filename: str):
    """
    Extrait toutes les informations nécessaires à la gestion des perturbations, et crée les objets correspondants
    """
    g_list, t_list, c_list, d_list, r_list, b_list, nb_days, deadline_days, LD, LF = get_variables(specs_filename,edt_filename+".json",data_filename)
    schedule = load_edt(edt_filename)

    return schedule, c_list, r_list, t_list, b_list, g_list, nb_days, deadline_days, LD, LF


