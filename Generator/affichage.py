from basics import ScheduleItem, Teacher
from typing import List
import os
import json

def recup_edt(solver, slot, courses, rooms, nb_days, nb_slots_per_day, verbose=False):
    # Reconstruction de l'edt = []
    schedule = []

    nb_rooms = len(rooms)

    for c in courses:
        for i in range(c.slots_per_week):

            value = solver.Value(slot[(c.id, i)])

            if value == -1: #Si solver partiel
                continue

            t = value // nb_rooms
            r_id = value % nb_rooms

            d = t // nb_slots_per_day
            s = t % nb_slots_per_day

            room = rooms[r_id]

            item = ScheduleItem(c.id, c.group, c.teacher, d, s, room.name)
            schedule.append(item)

            if verbose:
                print(f"Cours {c.id} | Groupe {c.group} | Prof {c.teacher.name} → d={d}, t={s}, salle={room.name}")

    return schedule  # schedule est une liste de ScheduleItem

########### PLUS BESOIN => PAS REFACTOR EN timeslot=(day,slot) donc ne fonctionnent plus!!!
# def affichage_eleves(schedule: List[ScheduleItem], sorted_timeslots, courses, rooms):
#     groups = sorted(set(item.group for item in schedule))
#     timeslots = sorted_timeslots

#     col_width = 16

#     # accès rapide
#     course_map = {c.id: c for c in courses}
#     room_map = {r.name: r for r in rooms}

#     edt = {
#         g: {t: "---" for t in timeslots}
#         for g in groups
#     }

#     for item in schedule:
#         c = course_map[item.course]
#         r = room_map[item.room]

#         # check validité
#         ok = (
#             r.capacity >= c.headcount
#             and any(rt in c.room_types for rt in r.room_types)
#         )

#         symbol = "✅" if ok else "❌"

#         edt[item.group][(item.day, item.slot)] = f"C{c.id}({r.name}){symbol}"

#     def separator():
#         return "+" + "+".join(["-" * col_width for _ in range(len(timeslots) + 1)]) + "+"

#     print(separator())
#     header = "|" + f"{'':<{col_width}}"
#     for t in timeslots:
#         header += f"|{'t'+str(t+1):<{col_width}}"
#     print(header + "|")
#     print(separator())

#     for g in groups:
#         row = f"|{g:<{col_width}}"
#         for t in timeslots:
#             row += f"|{edt[g][t]:<{col_width}}"
#         print(row + "|")

#     print(separator())


# def affichage_profs(schedule: List[ScheduleItem], sorted_timeslots, courses, rooms):
#     timeslots = sorted_timeslots

#     col_width = 18

#     # récupérer les profs uniques via leur id
#     teacher_map = {item.teacher.id: item.teacher for item in schedule}
#     teacher_ids = sorted(teacher_map.keys())

#     course_map = {c.id: c for c in courses}
#     room_map = {r.name: r for r in rooms}

#     edt = {
#         tid: {t: "---" for t in timeslots}
#         for tid in teacher_ids
#     }

#     for item in schedule:
#         c = course_map[item.course]
#         r = room_map[item.room]
#         tid = item.teacher.id

#         ok = (
#             r.capacity >= c.headcount
#             and any(rt in c.room_types for rt in r.room_types)
#         )

#         symbol = "✅" if ok else "❌"

#         edt[tid][(item.day, item.slot)] = f"C{c.id}({item.group},{r.name}){symbol}"

#     def separator():
#         return "+" + "+".join(["-" * col_width for _ in range(len(timeslots) + 1)]) + "+"

#     print(separator())

#     header = "|" + f"{'':<{col_width}}"
#     for t in timeslots:
#         header += f"|{'t'+str(t+1):<{col_width}}"
#     print(header + "|")
#     print(separator())

#     for tid in teacher_ids:
#         teacher = teacher_map[tid]

#         row = f"|{teacher.name:<{col_width}}"
#         for t in timeslots:
#             row += f"|{edt[tid][t]:<{col_width}}"
#         print(row + "|")

#     print(separator())


EDT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "EDT")

# ---------------------------------------------------------------------------
# Sauvegarde / chargement d'un EDT en JSON
# ---------------------------------------------------------------------------

def save_edt(schedule: List[ScheduleItem], name: str) -> str:
    """
    Sérialise l'emploi du temps (List[ScheduleItem]) en JSON et le sauvegarde.
    Cela permet de figer un EDT issu d'un run non-déterministe et de le recharger
    plus tard pour tester des scénarios de façon reproductible.

    Retourne le chemin du fichier créé.
    """
    os.makedirs(EDT_DIR, exist_ok=True)
    filepath = os.path.join(EDT_DIR, name + ".json")

    # ScheduleItem contient un Teacher (NamedTuple imbriqué) → on sérialise manuellement
    data = [
        {
            "course":  item.course,
            "group":   item.group,
            "teacher": {
                "id":      item.teacher.id,
                "name":    item.teacher.name,
                "courses": list(item.teacher.courses),
            },
            "day":   item.day,
            "slot":  item.slot,
            "room":  item.room,
        }
        for item in schedule
    ]

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"EDT sauvegardé : {filepath}")
    return filepath


def load_edt(name: str) -> List[ScheduleItem]:
    """
    Charge un EDT précédemment sauvegardé par save_edt.
    Retourne une List[ScheduleItem] prête à l'emploi (pour affichage ou scénarios).

    Paramètre
    ---------
    name : nom du fichier sans extension (ex: "lundi_run3")
    """
    filepath = os.path.join(EDT_DIR, name + ".json")

    with open(filepath, encoding="utf-8") as f:
        data = json.load(f)

    schedule = [
        ScheduleItem(
            course=  item["course"],
            group=   item["group"],
            teacher= Teacher(
                id=      item["teacher"]["id"],
                name=    item["teacher"]["name"],
                courses= item["teacher"]["courses"],
            ),
            day=  item["day"],
            slot= item["slot"],
            room= item["room"],
        )
        for item in data
    ]

    print(f"EDT chargé : {filepath}  ({len(schedule)} sessions)")
    return schedule


def save_edt_semestre(edts_by_week: list, name: str) -> str:
    """
    Sauvegarde un EDT semestre complet dans un seul fichier JSON.

    Format : liste plate de ScheduleItem, chacun enrichi d'un champ "week"
    indiquant la semaine (0-indexée) à laquelle appartient la session.

    Exemple d'un item sauvegardé :
        {"week": 2, "course": "1_w2_s0", "group": "A", "teacher": {...}, ...}

    Ce format permet de recharger l'EDT avec load_edt_semestre() et de
    reconstruire la structure semaine par semaine.

    Paramètres
    ----------
    edts_by_week : list de (week_index, List[ScheduleItem] ou None)
                   tel que retourné par la reconstruction dans main.py
    name : nom du fichier sans extension

    Retourne le chemin du fichier créé.
    """
    os.makedirs(EDT_DIR, exist_ok=True)
    filepath = os.path.join(EDT_DIR, name + ".json")

    data = []
    for week_idx, edt in edts_by_week:
        if edt is None:
            continue
        for item in edt:
            data.append({
                "week":   week_idx,
                "course": item.course,
                "group":  item.group,
                "teacher": {
                    "id":      item.teacher.id,
                    "name":    item.teacher.name,
                    "courses": list(item.teacher.courses),
                },
                "day":  item.day,
                "slot": item.slot,
                "room": item.room,
            })

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    nb_weeks_saved = len(set(d["week"] for d in data))
    print(f"EDT semestre sauvegardé : {filepath}  ({nb_weeks_saved} semaines, {len(data)} sessions)")
    return filepath


def load_edt_semestre(name: str) -> list:
    """
    Charge un EDT semestre sauvegardé par save_edt_semestre.

    Retourne une list de (week_index, List[ScheduleItem]),
    triée par semaine croissante — même format qu'edts_by_week dans main.py,
    ce qui permet de le passer directement à affichage_html_semestre().

    Les semaines sans session sont absentes de la liste retournée
    (elles n'avaient pas été sauvegardées).
    """
    filepath = os.path.join(EDT_DIR, name + ".json")

    with open(filepath, encoding="utf-8") as f:
        data = json.load(f)

    # Regrouper les items par semaine
    weeks: dict = {}
    for d in data:
        w = d["week"]
        if w not in weeks:
            weeks[w] = []
        weeks[w].append(ScheduleItem(
            course=  d["course"],
            group=   d["group"],
            teacher= Teacher(
                id=      d["teacher"]["id"],
                name=    d["teacher"]["name"],
                courses= d["teacher"]["courses"],
            ),
            day=  d["day"],
            slot= d["slot"],
            room= d["room"],
        ))

    edts_by_week = sorted(weeks.items())  # list de (week_idx, List[ScheduleItem])
    total = sum(len(edt) for _, edt in edts_by_week)
    print(f"EDT semestre chargé : {filepath}  ({len(edts_by_week)} semaines, {total} sessions)")
    return edts_by_week


def affichage_html_complet(schedule, nb_days, courses, rooms, filename="edt.html", lunch_slots=[2,3,4], nb_slots_per_day=10):
    os.makedirs(EDT_DIR, exist_ok=True)
    filepath = os.path.join(EDT_DIR, filename)

    # -------------------------
    # Préparation temps
    # -------------------------

    days_names = ["Lundi","Mardi","Mercredi","Jeudi","Vendredi"][:nb_days]

    # -------------------------
    # Données
    # -------------------------
    groups = sorted(set(item.group for item in schedule))
    teachers = sorted(set(item.teacher.id for item in schedule))
    teacher_map = {item.teacher.id: item.teacher for item in schedule}

    # Couleur par cours
    def color(course_id):
        return f"hsl({(course_id*40)%360}, 70%, 80%)"

    # Index
    edt_groups = {
        g: {(d,s): None for d in range(nb_days) for s in range(nb_slots_per_day)}
        for g in groups
    }

    edt_teachers = {
        tid: {(d,s): None for d in range(nb_days) for s in range(nb_slots_per_day)}
        for tid in teachers
    }

    for item in schedule:
        edt_groups[item.group][(item.day, item.slot)] = item
        edt_teachers[item.teacher.id][(item.day, item.slot)] = item

    # -------------------------
    # HTML
    # -------------------------
    html = """
    <html>
    <head>

    <style>
    body {
        font-family: Arial;
    }

    table {
        border-collapse: collapse;
        margin: 20px;
    }

    td, th {
        border: 1px solid black;
        text-align: center;
        width: 120px;
        height: 60px;
    }

    th {
        background-color: #ddd;
    }

    .hour {
        background-color: #f0f0f0;
        font-weight: bold;
    }

    /* Onglets */
    .tab {
        display: none;
    }

    .tab.active {
        display: block;
    }

    .tab-buttons button {
        margin: 5px;
        padding: 8px;
        cursor: pointer;
    }

    .lunch-header {
        background-color: #fff3cd;  /* jaune clair */
    }

    .hour {
        width: 80px;
    }


    </style>

    <script>
    function showTab(id){

        // CAS 1 : onglets principaux
        if(id === "groups" || id === "teachers") {

            document.getElementById("groups").classList.remove("active");
            document.getElementById("teachers").classList.remove("active");

            document.getElementById(id).classList.add("active");

            // activer premier sous-onglet
            if(id === "groups"){
                const first = document.querySelector("[id^='group_']");
                if(first) {
                    document.querySelectorAll("[id^='group_']").forEach(x => x.classList.remove("active"));
                    first.classList.add("active");
                }
            }

            if(id === "teachers"){
                const first = document.querySelector("[id^='teacher_']");
                if(first) {
                    document.querySelectorAll("[id^='teacher_']").forEach(x => x.classList.remove("active"));
                    first.classList.add("active");
                }
            }

        }

        // CAS 2 : sous-onglets groupes
        else if(id.startsWith("group_")) {

            document.querySelectorAll("[id^='group_']").forEach(x => x.classList.remove("active"));
            document.getElementById(id).classList.add("active");

        }

        // CAS 3 : sous-onglets profs
        else if(id.startsWith("teacher_")) {

            document.querySelectorAll("[id^='teacher_']").forEach(x => x.classList.remove("active"));
            document.getElementById(id).classList.add("active");

        }
    }
    </script>

    </head>

    <body>

    <h1>Emploi du temps</h1>

    <div class="tab-buttons">
        <button onclick="showTab('groups')">Groupes</button>
        <button onclick="showTab('teachers')">Profs</button>
    </div>
    """

    # ========
    # GROUPES 
    # ========
    html += "<div id='groups' class='tab active'>"
    html += "<h1>EDT GROUPES</h1>"

    # boutons groupes
    html += "<div class='tab-buttons'>"
    for g in groups:
        html += f"<button onclick=\"showTab('group_{g}')\">{g}</button>"
    html += "</div>"

    
    for i, g in enumerate(groups):
        active = "active" if i == 0 else ""
        html += f"<div id='group_{g}' class='tab {active}'>"

        html += f"<h2>Groupe {g}</h2><table>"

        # header
        html += "<tr><th></th>"
        for d in range(nb_days):
            html += f"<th>{days_names[d]}</th>"
        html += "</tr>"

        for h in range(nb_slots_per_day):
            is_lunch = h in lunch_slots
            if is_lunch:
                html += f"<tr><td class='hour lunch-header'>t{h+1} (Lunch)</td>"
            else:
                html += f"<tr><td class='hour'>t{h+1}</td>"

            for d in range(nb_days):
                item = edt_groups[g][(d,h)]

                if item:
                    color = f"hsl({(item.course*40)%360},70%,80%)"
                    html += f"""<td style="background:{color}">
                    C{item.course}<br>
                    {item.teacher.name} ({item.teacher.id})<br>
                    {item.room}
                    </td>"""
                else:
                    html += "<td></td>"

            html += "</tr>"

        html += "</table></div>"

    html += "</div>"

    # ======
    # PROFS
    # ======
    html += "<div id='teachers' class='tab'>"
    html += "<h1>EDT PROFS</h1>"

    # boutons profs
    html += "<div class='tab-buttons'>"
    for tid in teachers:
        teacher = teacher_map[tid]
        html += f"<button onclick=\"showTab('teacher_{tid}')\">{teacher.name}</button>"
    html += "</div>"

    
    for i, tid in enumerate(teachers):
        teacher = teacher_map[tid]
        active = "active" if i == 0 else ""
        html += f"<div id='teacher_{tid}' class='tab {active}'>"

        html += f"<h2>{teacher.name}</h2><table>"

        html += "<tr><th></th>"
        for d in range(nb_days):
            html += f"<th>{days_names[d]}</th>"
        html += "</tr>"

        for h in range(nb_slots_per_day):
            html += f"<tr><td class='hour'>t{h+1}</td>"

            for d in range(nb_days):
                item = edt_teachers[tid][(d,h)]

                if item:
                    color = f"hsl({(item.course*40)%360},70%,80%)"
                    html += f"""<td style="background:{color}">
                    C{item.course}<br>
                    {item.group}<br>
                    {item.room}
                    </td>"""
                else:
                    html += "<td></td>"

            html += "</tr>"

        html += "</table></div>"

    html += "</div>"
    html += "</body></html>"

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(html)

    print("Fichier généré :", filepath)

def affiche(input_file: str, nb_days, courses, rooms, lunch_slots, nb_slots_per_day, output:str=None):
    if output==None:
        output=input_file.split(".")[0]
    affichage_html_complet(load_edt(input_file), nb_days, courses, rooms, output, lunch_slots, nb_slots_per_day)


def affichage_html_semestre(
    edts_by_week: list,
    nb_days: int,
    courses,
    rooms,
    filename: str = "semestre.html",
    lunch_slots: list = None,
    nb_slots_per_day: int = 10,
    nb_weeks: int = 15,
):
    """
    Génère un fichier HTML visualisant l'EDT sur tout le semestre.

    Structure de l'interface :
        - Barre de navigation principale : onglet par semaine (S1, S2, ..., SN)
        - Dans chaque semaine : deux onglets "Groupes" et "Profs"
        - Dans "Groupes" : un sous-onglet par groupe
        - Dans "Profs"   : un sous-onglet par prof

    Paramètres
    ----------
    edts_by_week : list de (week_index, edt_ou_None)
                   edt = List[ScheduleItem] retourné par recup_edt()
    nb_days, courses, rooms, lunch_slots, nb_slots_per_day : paramètres de grille
    nb_weeks : nombre total de semaines (utilisé pour les labels)
    filename : nom du fichier HTML de sortie (sans chemin — sauvegardé dans EDT_DIR)
    """
    if lunch_slots is None:
        lunch_slots = [2, 3, 4]

    os.makedirs(EDT_DIR, exist_ok=True)
    filepath = os.path.join(EDT_DIR, filename)

    days_names = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi"][:nb_days]

    # ------------------------------------------------------------------
    # Collecte de tous les groupes et profs présents dans au moins une semaine
    # (pour construire les sous-onglets de façon cohérente)
    # ------------------------------------------------------------------
    all_groups = sorted(set(
        item.group
        for _, edt in edts_by_week if edt
        for item in edt
    ))
    all_teacher_ids = sorted(set(
        item.teacher.id
        for _, edt in edts_by_week if edt
        for item in edt
    ))
    teacher_name_by_id = {
        item.teacher.id: item.teacher.name
        for _, edt in edts_by_week if edt
        for item in edt
    }

    def cell_color(course_id):
        # En mode semestre, course_id est un string "1_w4_s2" → on extrait la partie numérique
        try:
            n = int(str(course_id).split("_")[0])
        except ValueError:
            n = abs(hash(str(course_id)))
        return f"hsl({(n * 40) % 360}, 70%, 80%)"

    # ------------------------------------------------------------------
    # Fonction utilitaire : génère le HTML d'une grille (tableau) pour
    # un groupe ou un prof donné, sur une semaine donnée.
    # Réutilisée pour chaque semaine × chaque groupe/prof.
    # ------------------------------------------------------------------
    def render_table(edt_index, slot_key):
        """
        edt_index : dict (day, slot) → ScheduleItem  (déjà indexé)
        slot_key  : "group" ou "teacher" (pour adapter le contenu de la cellule)
        """
        rows = ""
        for h in range(nb_slots_per_day):
            is_lunch = h in lunch_slots
            label = f"t{h+1} (Pause)" if is_lunch else f"t{h+1}"
            cls_hour = "hour lunch-header" if is_lunch else "hour"
            row = f"<tr><td class='{cls_hour}'>{label}</td>"
            for d in range(nb_days):
                item = edt_index.get((d, h))
                if item:
                    color = cell_color(item.course)
                    # En vue groupe : on affiche le prof et la salle
                    # En vue prof   : on affiche le groupe et la salle
                    if slot_key == "group":
                        detail = f"{item.teacher.name}<br>{item.room}"
                    else:
                        detail = f"{item.group}<br>{item.room}"
                    # On extrait le nom court du cours depuis l'id temporaire
                    # (format : "{course_id}_w{w}_s{i}" → on affiche juste course_id)
                    course_label = str(item.course).split("_")[0]
                    row += (
                        f"<td style='background:{color}'>"
                        f"<b>C{course_label}</b><br>{detail}"
                        f"</td>"
                    )
                else:
                    row += "<td></td>"
            rows += row + "</tr>"
        return rows

    # ------------------------------------------------------------------
    # Construction du HTML
    # ------------------------------------------------------------------
    html = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>EDT Semestre</title>
<style>
body { font-family: Arial, sans-serif; margin: 10px; }
h1   { font-size: 1.4em; }
h2   { font-size: 1.1em; margin: 6px 0; }

/* Grille */
table { border-collapse: collapse; margin: 10px 0; }
td, th { border: 1px solid #999; text-align: center;
          width: 120px; height: 55px; font-size: 0.8em; }
th     { background: #ddd; }
.hour  { background: #f0f0f0; font-weight: bold; width: 80px; }
.lunch-header { background: #fff3cd; }

/* Onglets génériques */
.tab { display: none; }
.tab.active { display: block; }

/* Barre de semaines */
.week-bar { display: flex; flex-wrap: wrap; gap: 4px; margin-bottom: 10px; }
.week-bar button {
    padding: 5px 10px; cursor: pointer; border: 1px solid #aaa;
    background: #eee; border-radius: 3px; font-size: 0.85em;
}
.week-bar button.active-btn { background: #4a90d9; color: white; border-color: #357abd; }

/* Barre groupes/profs à l'intérieur d'une semaine */
.inner-bar { display: flex; flex-wrap: wrap; gap: 4px; margin: 6px 0; }
.inner-bar button {
    padding: 4px 8px; cursor: pointer; border: 1px solid #ccc;
    background: #f8f8f8; border-radius: 3px; font-size: 0.8em;
}
.inner-bar button.active-btn { background: #5cb85c; color: white; border-color: #4cae4c; }

/* Barre entités (groupe ou prof) à l'intérieur d'une vue */
.entity-bar { display: flex; flex-wrap: wrap; gap: 3px; margin: 4px 0; }
.entity-bar button {
    padding: 3px 7px; cursor: pointer; border: 1px solid #ddd;
    background: #fafafa; border-radius: 2px; font-size: 0.75em;
}
.entity-bar button.active-btn { background: #f0ad4e; border-color: #eea236; }

.status-empty { color: #999; font-style: italic; padding: 20px; }
</style>

<script>
// ---------------------------------------------------------------
// showWeek(w)  : affiche la semaine w, masque les autres
// showView(w, v) : dans la semaine w, affiche "groups" ou "teachers"
// showEntity(w, v, id) : dans la semaine w et la vue v, affiche l'entité id
// ---------------------------------------------------------------

function clearActive(bar) {
    bar.querySelectorAll("button").forEach(b => b.classList.remove("active-btn"));
}

function showWeek(w) {
    // Masquer toutes les semaines
    document.querySelectorAll(".week-panel").forEach(p => p.classList.remove("active"));
    // Afficher la semaine choisie
    const panel = document.getElementById("week_" + w);
    if (panel) panel.classList.add("active");
    // Mettre à jour le bouton actif dans la barre de semaines
    const bar = document.getElementById("week-bar");
    clearActive(bar);
    const btn = bar.querySelector(`[data-week='${w}']`);
    if (btn) btn.classList.add("active-btn");
}

function showView(w, v) {
    // Masquer les deux vues (groups / teachers) de cette semaine
    ["groups", "teachers"].forEach(name => {
        const el = document.getElementById(`week_${w}_${name}`);
        if (el) el.classList.remove("active");
    });
    // Afficher la vue choisie
    const el = document.getElementById(`week_${w}_${v}`);
    if (el) el.classList.add("active");
    // Mettre à jour les boutons de la barre inner
    const bar = document.getElementById(`inner_bar_${w}`);
    clearActive(bar);
    const btn = bar.querySelector(`[data-view='${v}']`);
    if (btn) btn.classList.add("active-btn");
}

function showEntity(w, v, id) {
    // Masquer toutes les entités de cette vue
    document.querySelectorAll(`.entity_${w}_${v}`).forEach(p => p.classList.remove("active"));
    // Afficher l'entité choisie
    const el = document.getElementById(`entity_${w}_${v}_${id}`);
    if (el) el.classList.add("active");
    // Mettre à jour les boutons
    const bar = document.getElementById(`entity_bar_${w}_${v}`);
    clearActive(bar);
    const btn = bar.querySelector(`[data-entity='${id}']`);
    if (btn) btn.classList.add("active-btn");
}
</script>
</head>
<body>
<h1>Emploi du temps — Semestre complet</h1>
"""

    # Barre de navigation des semaines
    html += "<div class='week-bar' id='week-bar'>"
    for w_idx, edt in edts_by_week:
        label = f"S{w_idx + 1}"
        empty = " (vide)" if not edt else ""
        html += (
            f"<button data-week='{w_idx}' onclick='showWeek({w_idx})'>"
            f"{label}{empty}</button>"
        )
    html += "</div>\n"

    # ------------------------------------------------------------------
    # Panneau de chaque semaine
    # ------------------------------------------------------------------
    for week_pos, (w_idx, edt) in enumerate(edts_by_week):

        # Premier panneau actif par défaut
        active_week = "active" if week_pos == 0 else ""
        html += f"<div id='week_{w_idx}' class='week-panel tab {active_week}'>"
        html += f"<h2>Semaine {w_idx + 1}</h2>"

        if not edt:
            html += "<p class='status-empty'>Aucune session cette semaine.</p></div>\n"
            continue

        # Index rapide pour cette semaine
        edt_by_group = {
            g: {(d, s): None for d in range(nb_days) for s in range(nb_slots_per_day)}
            for g in all_groups
        }
        edt_by_teacher = {
            tid: {(d, s): None for d in range(nb_days) for s in range(nb_slots_per_day)}
            for tid in all_teacher_ids
        }
        for item in edt:
            if item.group in edt_by_group:
                edt_by_group[item.group][(item.day, item.slot)] = item
            if item.teacher.id in edt_by_teacher:
                edt_by_teacher[item.teacher.id][(item.day, item.slot)] = item

        # Barre "Groupes / Profs" pour cette semaine
        html += f"<div class='inner-bar' id='inner_bar_{w_idx}'>"
        html += (
            f"<button data-view='groups' onclick='showView({w_idx},\"groups\")'>Groupes</button>"
            f"<button data-view='teachers' onclick='showView({w_idx},\"teachers\")'>Profs</button>"
        )
        html += "</div>\n"

        # ---- Vue GROUPES ----
        html += f"<div id='week_{w_idx}_groups' class='tab active'>"
        html += f"<div class='entity-bar' id='entity_bar_{w_idx}_groups'>"
        for g in all_groups:
            html += (
                f"<button data-entity='{g}' "
                f"onclick='showEntity({w_idx},\"groups\",\"{g}\")'>{g}</button>"
            )
        html += "</div>\n"

        for g_pos, g in enumerate(all_groups):
            active_g = "active" if g_pos == 0 else ""
            html += (
                f"<div id='entity_{w_idx}_groups_{g}' "
                f"class='entity_{w_idx}_groups tab {active_g}'>"
            )
            html += f"<h2>Groupe {g} — Semaine {w_idx + 1}</h2>"
            html += "<table><tr><th></th>"
            for d in range(nb_days):
                html += f"<th>{days_names[d]}</th>"
            html += "</tr>"
            html += render_table(edt_by_group[g], "group")
            html += "</table></div>\n"

        html += "</div>\n"  # fin vue groups

        # ---- Vue PROFS ----
        html += f"<div id='week_{w_idx}_teachers' class='tab'>"
        html += f"<div class='entity-bar' id='entity_bar_{w_idx}_teachers'>"
        for tid in all_teacher_ids:
            name_t = teacher_name_by_id.get(tid, tid)
            html += (
                f"<button data-entity='{tid}' "
                f"onclick='showEntity({w_idx},\"teachers\",\"{tid}\")'>{name_t}</button>"
            )
        html += "</div>\n"

        for t_pos, tid in enumerate(all_teacher_ids):
            active_t = "active" if t_pos == 0 else ""
            name_t = teacher_name_by_id.get(tid, tid)
            html += (
                f"<div id='entity_{w_idx}_teachers_{tid}' "
                f"class='entity_{w_idx}_teachers tab {active_t}'>"
            )
            html += f"<h2>{name_t} — Semaine {w_idx + 1}</h2>"
            html += "<table><tr><th></th>"
            for d in range(nb_days):
                html += f"<th>{days_names[d]}</th>"
            html += "</tr>"
            html += render_table(edt_by_teacher[tid], "teacher")
            html += "</table></div>\n"

        html += "</div>\n"  # fin vue teachers
        html += "</div>\n"  # fin week panel

    # Script d'initialisation : activer la première semaine et ses sous-onglets
    html += """
<script>
// Activer la première semaine au chargement
(function() {
    const firstWeekBtn = document.querySelector(".week-bar button");
    if (firstWeekBtn) firstWeekBtn.classList.add("active-btn");
    // Activer le bouton "Groupes" de la première semaine visible
    const firstInner = document.querySelector(".week-panel.active .inner-bar button");
    if (firstInner) firstInner.classList.add("active-btn");
    // Activer la première entité groupe de la première semaine
    const firstEntity = document.querySelector(".week-panel.active .entity-bar button");
    if (firstEntity) firstEntity.classList.add("active-btn");
})();
</script>
</body></html>"""

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"HTML semestre généré : {filepath}")


# print(os.cpu_count())