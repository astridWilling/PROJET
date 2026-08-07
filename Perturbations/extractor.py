import os, csv, json
from basics import *
from gestion import *


# ===========================================================================
# CHARGEMENT DES SPECS
# ===========================================================================

def load_specs(filepath="Data/specs.json") -> dict:
    """
    Charge le fichier de specs statiques (bâtiments, salles, profs, cours, depts).
    Retourne un dict avec les clés : buildings, rooms, teachers, courses, departments.
    Si le fichier est absent, retourne des dicts vides → fallback CSV pour tout.
    """
    full_path = os.path.join(HERE, filepath)
    if not os.path.exists(full_path):
        print(f"[specs] Fichier '{filepath}' introuvable — déduction depuis le CSV uniquement.")
        return {"buildings": {}, "rooms": {}, "teachers": {}, "courses": {}, "departments": {}}

    with open(full_path, encoding="utf-8") as f:
        raw = json.load(f)

    specs = {
        # Indexés par ID/nom pour lookup O(1)
        "buildings":   {b["id"]:   b for b in raw.get("buildings",   [])},
        "rooms":       {r["name"]: r for r in raw.get("rooms",       [])},
        "teachers":    {t["name"]: t for t in raw.get("teachers",    [])},  # clé = nom (pour matcher le CSV)
        "courses":     {c["name"]: c for c in raw.get("courses",     [])},
        "departments": {d["id"]:   d for d in raw.get("departments", [])},
        "groups":      {g["id"]:   g for g in raw.get("groups",      [])},
    }
    print(f"[specs] Chargé : {len(specs['buildings'])} bâtiments, "
          f"{len(specs['rooms'])} salles, {len(specs['teachers'])} profs, "
          f"{len(specs['courses'])} cours, {len(specs['departments'])} depts."
          f" {len(specs['groups'])} groupes.")
    return specs


# ===========================================================================
# EXTRACTION PRINCIPALE
# ===========================================================================

def extraction(filepath="Data/edt_v2.csv", specs_filepath="Data/specs.json",
               affichage_html=False):
    """
    Construit les objets du domaine depuis le CSV EDT + le fichier specs.
    Priorité : specs.json > déductions CSV (les déductions sont conservées
    en commentaire pour traçabilité).
    """

    # -----------------------------------------------------------------------
    # 1. Chargement des specs
    # -----------------------------------------------------------------------
    specs = load_specs(specs_filepath)
    s_buildings = specs["buildings"]
    s_rooms     = specs["rooms"]
    s_teachers  = specs["teachers"]
    s_courses   = specs["courses"]
    s_groups    = specs["groups"]
    # -----------------------------------------------------------------------
    # 2. Lecture du CSV
    # -----------------------------------------------------------------------
    raw_data = []
    output_name = os.path.splitext(os.path.basename(filepath))[0]
    with open(os.path.join(HERE, filepath), encoding="utf-8") as f:
        reader = csv.reader(f, delimiter=";")
        next(reader)                            # ligne d'entête labels
        meta_row = next(reader)
        nb_days         = int(meta_row[0])
        LUNCH_DEBUT_MIN = hm(meta_row[1].strip())
        LUNCH_FIN_MIN   = hm(meta_row[2].strip())
        next(reader)                            # ligne d'entête colonnes

        for row in reader:
            if not any(row):
                continue
            coursename, teachername, group, building, roomname, day, hdebut, hfin, session_type = row
            raw_data.append((coursename, teachername, group, building, roomname,
                             int(day), hdebut.strip(), hfin.strip(), session_type.strip()))

    # -----------------------------------------------------------------------
    # 3. Construction des objets Room
    # -----------------------------------------------------------------------
    # Specs → capacité, types, bâtiment fiables.
    # Fallback CSV → déduit le type depuis le nom de salle et le bâtiment
    #                depuis la colonne building du CSV.
    rooms        = {}
    room_bat_csv = {}   # mémorise le bâtiment CSV pour les salles sans specs

    for coursename, teachername, group, building, roomname, day, hdebut, hfin, session_type in raw_data:
        if roomname == "_" or roomname in rooms:
            continue

        # Bâtiment : depuis le CSV (même valeur que ScheduleItem.building)
        bat_csv = building if building != "_" else "?"

        if roomname in s_rooms:
            # ── Specs disponibles ──────────────────────────────────────────
            sr = s_rooms[roomname]
            rooms[roomname] = Room(
                name=roomname,
                capacity=sr["capacity"],
                room_types=sr["room_types"],
                bat=sr.get("bat", bat_csv),
            )
        else:
            # ── Fallback CSV : déduction depuis le nom de salle ────────────
            # Logique originale conservée ici pour traçabilité :
            #   - "Vinci", "Riquet"               → CM,        bat depuis CSV
            #   - "GP1", "MFJA", contient "TP"    → TP,        bat depuis CSV
            #   - "Amphi111", "Amphi112"           → CM + TD,   bat depuis CSV
            #   - "Gym"                            → Sport,     bat depuis CSV
            #   - tout le reste                   → TD,        bat depuis CSV
            if roomname in ("Vinci", "Riquet"):
                rtypes = ["CM"]
            elif roomname in ("GP1", "MFJA") or "TP" in roomname:
                rtypes = ["TP"]
            elif roomname in ("Amphi111", "Amphi112"):
                rtypes = ["CM", "TD"]
            elif roomname == "Gym":
                rtypes = ["Sport"]
            else:
                rtypes = ["TD"]

            # Capacité : déduction très approximative depuis le CSV
            # (Vinci ≈ 300, Riquet ≈ 200, tout le reste ≈ 30 — à remplacer par les specs)
            if roomname == "Vinci":
                cap = 300
            elif roomname == "Riquet":
                cap = 200
            else:
                cap = 30

            rooms[roomname] = Room(name=roomname, capacity=cap,
                                   room_types=rtypes, bat=bat_csv)

    # Failsafe capacité : si un cours dépasse la capacité de la salle, on l'augmente.
    # Pratique arbitraire — à supprimer dès qu'on a les vraies capacités dans les specs.
    for coursename, teachername, group, building, roomname, day, hdebut, hfin, session_type in raw_data:
        if roomname == "_":
            continue
        hc = s_groups[group]["headcount"] if group in s_groups else 30
        r  = rooms[roomname]
        if hc > r.capacity:
            rooms[roomname] = r._replace(capacity=hc)

    # Charger les salles specs non présentes dans le CSV
    for rname, sr in s_rooms.items():
        if rname not in rooms:
            rooms[rname] = Room(
                name=rname,
                capacity=sr["capacity"],
                room_types=sr["room_types"],
                bat=sr.get("bat", "?"),
            )

    # -----------------------------------------------------------------------
    # 4. Construction des objets Building
    # -----------------------------------------------------------------------
    # Specs → distances réelles entre bâtiments.
    # Fallback CSV → bâtiment découvert via la colonne building, distances toutes à 5 min
    #                (sauf Gym=10, MFJA=35 — valeurs qu'on savait hardcoder).
    buildings = {}

    for coursename, teachername, group, building, roomname, day, hdebut, hfin, session_type in raw_data:
        if building == "_" or building in buildings:
            continue

        if building in s_buildings:
            # ── Specs disponibles ──────────────────────────────────────────
            sb = s_buildings[building]
            buildings[building] = Building(
                id=building,
                name=sb.get("name", building),
                rooms=[],
                dist=dict(sb.get("dist", {})),
            )
        else:
            # ── Fallback CSV : bâtiment découvert dans le CSV ──────────────
            # Distance inconnue → 5.0 min par défaut pour tous les voisins.
            # Exceptions connues hardcodées : Gym=10, MFJA=35.
            buildings[building] = Building(id=building, name=building,
                                           rooms=[], dist={})

    # Relier les salles à leur bâtiment (lookup direct, pas de boucle raw_data)
    for roomname, room in rooms.items():
        bat = room.bat
        if bat and bat != "?" and bat in buildings:
            if room not in buildings[bat].rooms:
                buildings[bat].rooms.append(room)

    # Remplir les distances manquantes pour les bâtiments sans specs
    for bid, b in buildings.items():
        for other_bid in buildings:
            if other_bid != bid and other_bid not in b.dist:
                # Fallback CSV : 5 min par défaut, Gym et MFJA connus
                # (à remplacer par les vraies valeurs dans specs.json)
                if other_bid == "Gym":
                    b.dist[other_bid] = 10.0
                elif other_bid == "MFJA":
                    b.dist[other_bid] = 35.0
                else:
                    b.dist[other_bid] = 5.0

    # -----------------------------------------------------------------------
    # 5. Construction des objets Group 
    # -----------------------------------------------------------------------
    groups_map = {}
    sorted_gspecs = sorted(s_groups.values(), key=lambda g: 0 if not g.get("parent_id") else 1)
    for g_spec in sorted_gspecs:
        parent_obj = groups_map.get(g_spec.get("parent_id"))
        groups_map[g_spec["id"]] = Group(
            id=g_spec["id"],
            headcount=g_spec["headcount"],
            parent=parent_obj,
            subgroup_ids=g_spec.get("subgroup_ids"),
        )

    # -----------------------------------------------------------------------
    # 6. Construction des objets Teacher
    # -----------------------------------------------------------------------
    # Specs → teacher_type, max_hours, possible_classes, dept.
    # Fallback CSV : teacher créé avec tous ces champs à None (inconnus).
    teachers     = {}
    next_course_id = 1
    course_index   = {}
    courses        = {}

    for coursename, teachername, group, building, roomname, day, hdebut, hfin, session_type in raw_data:
        if teachername in teachers:
            continue

        if teachername in s_teachers:
            # ── Specs disponibles ──────────────────────────────────────────
            st = s_teachers[teachername]
            # possible_classes : les clés sont des noms de cours dans le JSON,
            # on les convertira en IDs après avoir construit le course_index.
            teachers[teachername] = Teacher(
                id=st.get("id", f"T_{teachername}"),
                name=teachername,
                courses=[],
                teacher_type=st.get("teacher_type"),
                max_hours=st.get("max_hours"),
                possible_classes=st.get("possible_classes") or {},
                dept=st.get("dept"),
            )
        else:
            # ── Fallback CSV : prof découvert dans le CSV ──────────────────
            # Type, quota, compétences et département inconnus → None.
            # À compléter dans specs.json au fur et à mesure.
            teachers[teachername] = Teacher(
                id=f"T_{teachername}",
                name=teachername,
                courses=[],
            )

    # Profs définis dans specs.json mais absents du CSV (ex : remplaçants potentiels)
    for teachername, st in s_teachers.items():
        if teachername not in teachers:
            teachers[teachername] = Teacher(
                id=st.get("id", f"T_{teachername}"),
                name=teachername,
                courses=[],
                teacher_type=st.get("teacher_type"),
                max_hours=st.get("max_hours"),
                possible_classes=st.get("possible_classes") or {},
                dept=st.get("dept"),
            )

    # -----------------------------------------------------------------------
    # 7. Construction des objets Course
    # -----------------------------------------------------------------------
    # Specs → dept, room_types fiables.
    # Fallback CSV : room_types déduit depuis session_type de la première occurrence,
    #                dept inconnu (None).
    deadline_days = {}
    for coursename, teachername, group, building, roomname, day, hdebut, hfin, session_type in raw_data:
        key = (coursename, group)
        if key in courses:
            continue

        course_id = next_course_id
        next_course_id += 1
        course_index[key] = course_id

        if coursename in s_courses:
            # ── Specs disponibles ──────────────────────────────────────────
            sc = s_courses[coursename]
            courses[key] = Course(
                id=course_id,
                name=coursename,
                teacher=teachers[teachername],
                group_ids=[group],
                room_types=sc.get("room_types", [session_type]),
                slots_per_week=0,
                dept=sc.get("dept"),
                preferred_buildings=sc.get("preferred_buildings", []),
            )
            if sc.get("exam_day") is not None:
                deadline_days[course_id] = sc["exam_day"]
        else:
            # ── Fallback CSV : room_type déduit depuis session_type ────────
            courses[key] = Course(
                id=course_id,
                name=coursename,
                teacher=teachers[teachername],
                group_ids=[group],
                room_types=[session_type],
                slots_per_week=0,
            )
        teachers[teachername].courses.append(course_id)

    # slots_per_week : toujours compté depuis le CSV
    counter = defaultdict(int)
    for coursename, teachername, group, building, roomname, day, hdebut, hfin, session_type in raw_data:
        counter[(coursename, group)] += 1
    for key in courses:
        courses[key] = courses[key]._replace(slots_per_week=counter[key])

    # -----------------------------------------------------------------------
    # 8. Convertir possible_classes {nom_cours: score} → {course_id: score}
    # -----------------------------------------------------------------------
    # Les specs stockent les noms de cours (lisibles), on les traduit en IDs.
    # Un nom de cours peut couvrir plusieurs groupes → on prend tous les IDs.
    name_to_ids: dict = defaultdict(list)
    for (cname, _group), c in courses.items():
        name_to_ids[cname].append(c.id)

    for teachername, teacher in teachers.items():
        if not teacher.possible_classes:
            continue
        converted = {}
        for cname_or_id, score in teacher.possible_classes.items():
            if cname_or_id in name_to_ids:
                for cid in name_to_ids[cname_or_id]:
                    converted[cid] = score
            else:
                # Déjà un ID numérique (ou inconnu) — on garde tel quel
                try:
                    converted[int(cname_or_id)] = score
                except (ValueError, TypeError):
                    converted[cname_or_id] = score
        teachers[teachername] = teacher._replace(possible_classes=converted)

    # -----------------------------------------------------------------------
    # 9. Construction des objets Department
    # -----------------------------------------------------------------------
    departments = {}
    for dept_id, dept_data in specs["departments"].items():
        t_ids = [t.id for t in teachers.values() if t.dept == dept_id]
        c_ids = [c.id for c in courses.values() if c.dept == dept_id]
        departments[dept_id] = Department(
            id=dept_id,
            name=dept_data.get("name", dept_id),
            teacher_ids=t_ids,
            course_ids=c_ids,
        )

    # -----------------------------------------------------------------------
    # 10. Construction des ScheduleItems
    # -----------------------------------------------------------------------
    schedule_items = []
    for coursename, teachername, group, building, roomname, day, hdebut, hfin, session_type in raw_data:
        key          = (coursename, group)
        course_id    = course_index[key]
        teacher      = teachers[teachername]
        room_str     = roomname if roomname != "_" else "?"
        building_str = building if building != "_" else "?"
        g_obj = groups_map.get(group)
        sess_type = [typ for typ in s_courses[coursename].get("room_types") if session_type in typ]
        schedule_items.append(ScheduleItem(
            course=course_id,
            group=[g_obj] if g_obj else [],
            teacher=teacher,
            day=day, heure_debut=hdebut, heure_fin=hfin,
            room=room_str, building=building_str,
            session_type=sess_type[0] if sess_type else session_type,
        ))
    # -----------------------------------------------------------------------
    # 10b. Fusion des sessions partagées (même prof/créneau/salle → 1 item)
    # -----------------------------------------------------------------------
    # Un CM partagé entre 3 groupes génère 3 lignes CSV → 3 ScheduleItems.
    # On les fusionne en un seul item avec item.group = [G1, G2, G3] pour que
    # _assign_lanes ne les détecte pas comme conflits dans la vue prof/salle.
    merged_items: dict = {}
    for item in schedule_items:
        key = (item.teacher.id, item.day, hm(item.heure_debut), hm(item.heure_fin), item.room)
        if key in merged_items:
            existing = merged_items[key]
            merged_items[key] = existing._replace(group=existing.group + item.group)
        else:
            merged_items[key] = item
    schedule_items = list(merged_items.values())

    # -----------------------------------------------------------------------
    # 11. Sauvegarde + HTML
    # -----------------------------------------------------------------------
    # save_edt(schedule_items, output_name) # Déjà sauvegardé la première fois donc pas besoin de le faire a chaque fois

    if affichage_html:
        affichage_html_complet(schedule_items, nb_days=nb_days,
                               courses=list(courses.values()), rooms=list(rooms.values()),
                               filename=output_name+".html",
                               lunch_debut_min=LUNCH_DEBUT_MIN, lunch_fin_min=LUNCH_FIN_MIN,
                               deadline_days=deadline_days or None)

    edt           = load_edt(output_name, groups_map=groups_map)
    courses_list  = list(courses.values())
    rooms_list    = list(rooms.values())
    teachers_list = list(teachers.values())
    buildings_list = list(buildings.values())
    depts_list    = list(departments.values())
    groups_list   = list(groups_map.values())

    return edt, courses_list, rooms_list, teachers_list, buildings_list, groups_list, nb_days, deadline_days, LUNCH_DEBUT_MIN, LUNCH_FIN_MIN
