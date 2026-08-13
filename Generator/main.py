import os
from solver import solve
from term_solver import term_solve
from scenarios import teacher_absent, room_unavailable, build_soft_scorers
from basics import Room, Teacher, Course, Building, NoSolution, TimeOut
from affichage import affichage_html_complet, affichage_html_semestre, recup_edt, save_edt, load_edt, save_edt_semestre, load_edt_semestre
from constraints import ALL_CONSTRAINTS
import json
import time
from log import logging, run_all_experiments, load_constraints_from_log, run_diff_timeout, get_log_entry, run_cp_experiment
from analyze_log import list_cp_experiments, plot_cp_experiment, analyze_semester, compare_semester
import datetime

#################################################
##### FONCTION POUR LIRE A PARTIR D'UN JSON #####
#################################################


def load_input(filepath: str):
    with open(filepath, encoding="utf-8") as f:
        data = json.load(f)

    rooms = [
        Room(r["name"], r["capacity"], r["room_types"], r.get("bat", "default"))
        for r in data["rooms"]
    ]

    teachers = {
        t["id"]: Teacher(t["id"], t["name"], [])
        for t in data["teachers"]
    }

    group_size = {g["id"]: g["size"] for g in data["groups"]}

    courses = [
        Course(
            id=c["id"],
            name=c["name"],
            teacher=teachers[c["teacher"]],
            group=c["group"],
            headcount=group_size[c["group"]],
            room_types=c["room_types"],
            slots_per_week=c["slots_per_week"],
            session_room_types=c.get("session_room_types"),    # None si absent
            ordering_preference=c.get("ordering_preference"), # None si absent
        )
        for c in data["courses"]
    ]

    buildings_data = data.get("buildings", [])
    if buildings_data and isinstance(buildings_data, list) and isinstance(buildings_data[0], dict) and "dist" in buildings_data[0]:
        rooms_by_bat = {}
        for r in rooms:
            rooms_by_bat.setdefault(r.bat, []).append(r)
        buildings = [
            Building(b["id"], b["name"], rooms_by_bat.get(b["id"], []), b["dist"])
            for b in buildings_data
        ]
    else:
        buildings = None

    # sessions_map : dict course_id → ["CM", "TD", ...] pour les cours qui définissent
    # une séquence ordonnée sur le semestre. Vide si aucun cours n'a ce champ.
    sessions_map = {
        c["id"]: c["sessions"]
        for c in data["courses"]
        if "sessions" in c
    }

    return courses, rooms, list(teachers.values()), buildings, sessions_map

# input_data = "Data/instance_petite.json"
# input_data = "Data/instance_moyenne.json"
# input_data="Data/instance_complexe.json"
# input_data="Data/instance_univ.json"
# input_data = "Data/instance_real-univ.json"

# courses, rooms, teachers = load_input(input_data)

#Param pour petite et moyenne
# nb_days = 3
# nb_slots_per_day = 10
# lunch_slots = [2, 3, 4]

#Param pour sorbonne_large
nb_days = 5
nb_slots_per_day = 8
lunch_slots = [3, 4]

config = [
    {
        "name": "LongLunch",
        "is_hard": False,
        "is_active": True,
        "weight": 3,
        "lunch_slots": lunch_slots,
        "nb_slots_per_day": nb_slots_per_day
    },
    {
        "name": "NoGap",
        "is_hard": False,
        "is_active": True,
        "weight": 1,
        "lunch_slots": lunch_slots,
        "nb_slots_per_day": nb_slots_per_day
    },
    {
        "name": "NoLateDay",
        "is_hard": False,
        "is_active": True,
        "weight": 2,
        "lunch_slots": lunch_slots,
        "nb_slots_per_day": nb_slots_per_day
    },
    {
        "name": "LongLunchTeacher",
        "is_hard": False,
        "is_active": True,
        "weight": 3,
        "lunch_slots": lunch_slots,
        "nb_slots_per_day": nb_slots_per_day
    },
    {
        "name": "NoLateDayTeacher",
        "is_hard": False,
        "is_active": True,
        "weight": 2,
        "lunch_slots": lunch_slots,
        "nb_slots_per_day": nb_slots_per_day
    },
    {
        "name": "Closer",
        "is_hard": False,
        "is_active": True,
        "weight": 3,
        "lunch_slots": lunch_slots,
        "nb_slots_per_day": nb_slots_per_day,
        "threshold": 5
    },
    {
        "name": "CloserTeacher",
        "is_hard": False,
        "is_active": True,
        "weight": 3,
        "lunch_slots": lunch_slots,
        "nb_slots_per_day": nb_slots_per_day,
        "threshold": 5
    },
]



if __name__=="__main__":
    import sys
    sys.stdin.reconfigure(encoding="utf-8",  errors="surrogateescape")
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    try:
        # ----------------------------------------------------------------
        # Branche SEMESTRE : résolution sur toutes les semaines
        # Disponible uniquement si les cours de l'instance définissent
        # un champ "sessions" (séquence ordonnée sur le semestre).
        # ----------------------------------------------------------------
        semester_ans = input(">>> Mode semestre (résolution sur N semaines) ? [Y/N] > ")
        if semester_ans.lower() in ("y", "yes", ""):
            input_data = input("Donner le chemin vers le fichier d'instance > ")
            courses, rooms, teachers, buildings, sessions_map = load_input(input_data)

            if not sessions_map:
                print("[!] Aucun cours ne définit de séquence 'sessions' dans ce fichier.")
                print("    Ajoutez un champ \"sessions\": [\"CM\", \"TD\", ...] dans les cours du JSON.")
            else:
                print(f"  {len(sessions_map)} cours avec séquence définie sur {len(courses)} cours total.")

                constraints = []
                for c in config:
                    cls = ALL_CONSTRAINTS[c["name"]]
                    kwargs = {
                        "is_hard": c["is_hard"],
                        "is_active": c["is_active"],
                        "weight": c["weight"],
                        "lunch_slots": c["lunch_slots"],
                        "nb_slots_per_day": c["nb_slots_per_day"],
                    }
                    if "threshold" in c:
                        kwargs["threshold"] = c["threshold"]
                    constraints.append(cls(**kwargs))

                nb_weeks = int(input("Nombre de semaines du semestre (ex: 15) > ").strip() or "15")

                t = input("Timeout par semaine en secondes (rien=60) > ")
                timeout = int(t) if t.strip() else 60

                wt = input("Timeout pour l'assignation aux semaines / week_solve (rien=60) > ")
                week_solve_timeout = int(wt) if wt.strip() else 60

                w = input(f"Nombre de threads CPU (dispo : {os.cpu_count()}, rien=4) > ")
                num_workers = int(w) if w.strip() else 4

                # Calculer la charge moyenne par groupe pour aider l'utilisateur
                import math
                _spg = {}
                for c in courses:
                    n = len(sessions_map.get(c.id, []))
                    _spg[c.group] = _spg.get(c.group, 0) + n
                if _spg:
                    max_per_group = max(_spg.values()) / nb_weeks  # On prend le max plutot que simplement la moyenne
                    _auto = math.ceil(max_per_group * 1.1)
                    print(f"  (max séances/groupe/semaine → auto={_auto})")
                else:
                    _auto = 8
                max_w = input("Nb max de sessions par groupe par semaine (rien=auto) > ")
                max_sessions = int(max_w) if max_w.strip() else None

                ow = input("Poids des préférences early/late/middle (rien=2) > ")
                ordering_weight = int(ow) if ow.strip() else 2

                bw = input("Poids de l'équilibre des semaines balance_weight (rien=2) > ")
                balance_weight = int(bw) if bw.strip() else 2

                pw = input("Pénalité si on inverse 2 cours par rapport a l'ordre souhaite par le prof (rien=2) > ")
                order_penalty = int(pw) if pw.strip() else 2

                now = datetime.datetime.now()
                eta_seconds = nb_weeks * timeout + week_solve_timeout
                print(f"\nDébut ({now.strftime('%H:%M:%S')}) → ETA max : "
                      f"{(now + datetime.timedelta(seconds=eta_seconds)).strftime('%H:%M:%S')}")

                start = time.time()
                results, ws_meta, all_unplaced = term_solve(
                    courses, rooms, sessions_map, nb_weeks, nb_days,
                    lunch_slots=lunch_slots,
                    nb_slots_per_day=nb_slots_per_day,
                    constraints=constraints,
                    timeout=timeout,
                    week_solve_timeout=week_solve_timeout,
                    buildings=buildings,
                    num_workers=num_workers,
                    max_sessions_per_group_per_week=max_sessions,
                    balance_weight=balance_weight,
                    ordering_weight=ordering_weight,
                )
                duration = time.time() - start
                print(f"\nDurée totale : {int(duration // 60)}m {duration % 60:.2f}s")

                # Reconstruire les EDTs semaine par semaine
                edts_by_week = []
                for w_idx, result in results:
                    if result is None:
                        edts_by_week.append((w_idx, None))
                    else:
                        solver_obj, slot, temp_courses, status, score, fallback_edt = result
                        if fallback_edt is not None:
                            # Niveau 3 greedy : schedule déjà construit, pas besoin de recup_edt
                            edts_by_week.append((w_idx, fallback_edt))
                        elif status in ("OPTIMAL", "FEASIBLE"):
                            edt = recup_edt(solver_obj, slot, temp_courses, rooms,
                                            nb_days, nb_slots_per_day)
                            edts_by_week.append((w_idx, edt))
                        else:
                            edts_by_week.append((w_idx, None))

                # Sauvegarde automatique de tout le semestre dans un seul JSON
                nb_solved = sum(1 for _, edt in edts_by_week if edt is not None)
                print(f"  ({nb_solved}/{nb_weeks} semaines avec un EDT exploitable)")
                sem_name = input("\nNom de l'EDT semestre à sauvegarder (sans extension, vide = ne pas sauvegarder) > ").strip()
                if sem_name:
                    save_edt_semestre(edts_by_week, sem_name)

                # Log — status agrégé
                week_statuses = [r[3] for _, r in results if r is not None]
                if week_statuses and all(s == "OPTIMAL" for s in week_statuses):
                    global_status = "OPTIMAL"
                elif any(s in ("OPTIMAL", "FEASIBLE", "GREEDY") for s in week_statuses):
                    global_status = "FEASIBLE"
                else:
                    global_status = "UNKNOWN"
                global_score = sum(
                    r[4] for _, r in results
                    if r is not None and r[4] is not None
                )

                # Détail par semaine pour le log
                weeks_log = []
                for w_idx, r in results:
                    if r is None:
                        weeks_log.append({"week": w_idx, "status": "MISSING", "score": None})
                    else:
                        weeks_log.append({
                            "week":   w_idx,
                            "status": r[3],
                            "score":  r[4],
                            "greedy": r[3] == "GREEDY",
                        })

                # Répartition : nb sessions par semaine d'après les résultats du solve
                repartition_log = {
                    w_idx: len(r[2]) if r is not None else 0
                    for w_idx, r in results
                }

                logging(
                    input_data=input_data,
                    constraints=constraints,
                    status=global_status,
                    score=global_score,
                    max_searchtime=timeout,
                    duration=duration,
                    output=sem_name or None,
                    nb_days=nb_days,
                    nb_slots_per_day=nb_slots_per_day,
                    lunch_slots=lunch_slots,
                    num_workers=num_workers,
                    nb_weeks=nb_weeks,
                    is_semester=True,
                    weeks=weeks_log,
                    repartition=repartition_log,
                    balance_weight=balance_weight,
                    ordering_weight=ordering_weight,
                    order_penalty=order_penalty,
                    max_sessions_per_group_per_week=max_sessions,
                    timeout_week_solve=week_solve_timeout,
                    timeout_per_week=timeout,
                    week_solve_status=ws_meta["status"],
                    week_solve_objective=ws_meta["objective"],
                    nb_unplaced=len(all_unplaced),
                )
                print("Log enregistré dans Logs/log.json")

                html_ans = input("Générer le HTML semestre pour visualiser ? [Y/N] > ")
                if html_ans.lower() in ("y", "yes", ""):
                    affichage_html_semestre(
                        edts_by_week, nb_days, courses, rooms,
                        sem_name + ".html", lunch_slots, nb_slots_per_day, nb_weeks
                    )

        else:
            # ----------------------------------------------------------------
            # Branche SCÉNARIO SEMESTRE : charger un EDT semestre existant
            # ----------------------------------------------------------------
            scen_sem_ans = input(">>> Charger un EDT semestre pour appliquer un scénario ? [Y/N] > ")
            if scen_sem_ans.lower() in ("y", "yes", ""):
                sem_edt_name = input(">>> Nom de l'EDT semestre à charger (sans extension) : > ").strip()
                edts_by_week = load_edt_semestre(sem_edt_name)

                # Recharger l'instance depuis le log du run d'origine
                log_entry = get_log_entry(sem_edt_name)
                if log_entry is None:
                    raise ValueError(f"Aucune entrée de log pour '{sem_edt_name}' — impossible de récupérer l'instance.")
                input_data_scen  = log_entry["input"]
                nb_days_scen     = log_entry.get("nb_days",          nb_days)
                nb_slots_scen    = log_entry.get("nb_slots_per_day", nb_slots_per_day)
                lunch_slots_scen = log_entry.get("lunch_slots",      lunch_slots)
                courses_scen, rooms_scen, _, _buildings_scen, _ = load_input(input_data_scen)
                print(f"Instance chargée : {input_data_scen}  ({nb_days_scen}j x {nb_slots_scen} slots)")

                log_constraints = log_entry.get("constraints", [])
                soft_scorers = build_soft_scorers(log_constraints) if log_constraints else None
                if not soft_scorers:
                    print("[!] Pas de contraintes dans le log — placement greedy pur.")

                # Scénarios semestre disponibles
                print("Scénarios disponibles : [1] Prof absent  [0] Aucun")
                scenario_sem = input(">>> Choix : > ").strip()

                if scenario_sem == "1":
                    tid = input(">>> ID du prof absent (ex: T1) : > ").strip()
                    print(">>> Créneaux d'absence : format 'semaine,jour,slot' séparés par espaces")
                    print("    (tout 0-indexé — semaine 0 = première semaine, ex: 0,0,3 3,3,8)")
                    raw = input(">>> > ").strip()

                    # Parse → {semaine_0idx: [(day, slot), ...]}
                    absences_by_week: dict = {}
                    for token in raw.split():
                        parts = token.split(",")
                        w, day, slot = int(parts[0]), int(parts[1]), int(parts[2])
                        absences_by_week.setdefault(w, []).append((day, slot))

                    # Pour chaque semaine concernée, on applique teacher_absent
                    modified_by_week = dict(edts_by_week)  # {w: schedule ou None}
                    total_cancelled = []

                    for w, absent_slots in sorted(absences_by_week.items()):
                        week_schedule = modified_by_week.get(w)
                        if week_schedule is None:
                            print(f"  [!] Semaine {w+1} : aucun EDT disponible, impossible d'appliquer le scénario.")
                            continue
                        print(f"\n  Semaine {w+1} — {len(absent_slots)} créneau(x) d'absence...")
                        new_week, cancelled = teacher_absent(
                            week_schedule, courses_scen, rooms_scen,
                            nb_days_scen, nb_slots_scen,
                            teacher_id=tid,
                            absent_slots=absent_slots,
                            lunch_slots=lunch_slots_scen,
                            soft_scorers=soft_scorers,
                        )
                        modified_by_week[w] = new_week
                        total_cancelled.extend(cancelled)

                    # Résumé
                    if total_cancelled:
                        print(f"\n{len(total_cancelled)} session(s) non replanifiable(s) :")
                        for c in total_cancelled:
                            print(f"  - Semaine ? cours {c.course} ({c.group}) jour {c.day} slot {c.slot}")
                    else:
                        print("\nToutes les sessions ont été replanifiees.")

                    # Reconstruire la liste triée pour save/affichage
                    edts_by_week_new = sorted(modified_by_week.items())

                    new_sem_name = input("\nNom du nouvel EDT semestre (sans extension, vide = ne pas sauvegarder) : > ").strip()
                    if new_sem_name:
                        save_edt_semestre(edts_by_week_new, new_sem_name)
                    if input("Générer le HTML semestre ? [Y/N] > ").lower() in ("y", "yes", ""):
                        html_sem_name = new_sem_name or (sem_edt_name + f"_{tid}_absent")
                        affichage_html_semestre(
                            edts_by_week_new, nb_days_scen, courses_scen, rooms_scen,
                            html_sem_name + ".html", lunch_slots_scen, nb_slots_scen,
                            nb_weeks=len(edts_by_week_new),
                        )

            else:
                affiche_semestre = input(">>> Afficher des résultats d'un edt de semestre ? [Y/N] > ")
                # ----------------------------------------------------------------
                # Branche AFFICHAGE DE SEMESTRE
                # ----------------------------------------------------------------
                if affiche_semestre.lower() in ("y", "yes", ""):
                    inst = input(">>> Filtrer sur une instance particulière (chemin exact, vide = toutes) > ").strip() or None
                    print(f"Voici la liste des études de convergence disponibles pour l'instance '{inst}':")
                    analyze_semester(inst)
                    compare_ans = input(">>> Comparer deux instances ? [Y/N] > ")
                    if compare_ans.lower() in ("y", "yes", ""):
                        inst1 = input(">>> Première instance (chemin exact) > ").strip()
                        inst2 = input(">>> Deuxième instance (chemin exact) > ").strip()
                        compare_semester(inst1, inst2)
                
                else:
                    # ----------------------------------------------------------------
                    # Branche SEMAINE UNIQUE
                    # ----------------------------------------------------------------
                    run = input(">>> Run une instance avec la config et les param du main ? [Y/N] > ")
                    # ----------------------------------------------------------------
                    # Branche RÉSOLUTION : on lance le solver
                    # ----------------------------------------------------------------
                    if run.lower() in ("y","yes", ""):
                        input_data = input("Donner le chemin vers le fichier d'instance > ")
                        courses, rooms, teachers, buildings, sessions_map = load_input(input_data)

                        constraints = []
                        for c in config:
                            cls = ALL_CONSTRAINTS[c["name"]]
                            kwargs = {
                                "is_hard": c["is_hard"],
                                "is_active": c["is_active"],
                                "weight": c["weight"],
                                "lunch_slots": c["lunch_slots"],
                                "nb_slots_per_day": c["nb_slots_per_day"],
                            }
                            if "threshold" in c:
                                kwargs["threshold"] = c["threshold"]
                            constraints.append(cls(**kwargs))

                        t = input("Donner la valeur du timeout (durée max de recherche, rien=60) > ")
                        if t=="":
                            timeout=60
                        else:
                            timeout=int(t)

                        w = input(f"Nombre de threads CPU à utiliser (dispo : {os.cpu_count()}, rien=4) > ")
                        num_workers = int(w) if w.strip() else 4

                        now = datetime.datetime.now()
                        print(f"Début de la résolution ({now.strftime('%H:%M:%S')}) -> ETA : {(now + datetime.timedelta(seconds=timeout)).strftime('%H:%M:%S')}")
                        start = time.time()
                        solver, slot, _, _, status, score, max_searchtime, _ = solve(
                                        courses, rooms, nb_days, lunch_slots, nb_slots_per_day, constraints, timeout,
                                        buildings=buildings, num_workers=num_workers
                                    )
                        end = time.time()
                        duration = end - start

                        edt = recup_edt(solver, slot, courses, rooms, nb_days, nb_slots_per_day) \
                                        if status in ["OPTIMAL", "FEASIBLE"] else None

                        print(f"Durée : {int(duration // 60)}m {duration % 60:.2f}s  |  Status : {status}")

                        # Log systématique, même si UNKNOWN ou sans sauvegarde
                        name = None
                        if edt is not None:
                            name = input("Nom de l'EDT (sans extension, vide = ne pas sauvegarder) : > ").strip() or None
                            if name:
                                save_edt(edt, name)
                                html_ans = input("Générer le HTML pour visualiser ? [Y/N] > ")
                                if html_ans.lower() in ("y", "yes"):
                                    affichage_html_complet(edt, nb_days, courses, rooms,
                                                        name + ".html", lunch_slots, nb_slots_per_day)

                        logging(input_data=input_data, constraints=constraints, status=status,
                                score=score, max_searchtime=max_searchtime, duration=duration, output=name,
                                nb_days=nb_days, nb_slots_per_day=nb_slots_per_day, lunch_slots=lunch_slots,
                                num_workers=num_workers)
                        print("Log enregistré dans Logs/log.json")

                    else:
                        ans=input(">>> Run TOUTES les config de soft possibles? [Y/N] > ")

                        # ----------------------------------------------------------------
                        # Branche GROS RUN : on lance run_all_experiments
                        # ----------------------------------------------------------------
                        if (ans.lower()=="y") or (ans.lower()=="yes") or (ans.lower()==""):
                            filepath=input(">>> Donner le chemin vers le fichier d'instance > ")
                            courses, rooms, teachers, buildings, sessions_map = load_input(filepath)
                            run_all_experiments(filepath, config, courses, rooms, nb_days, lunch_slots, nb_slots_per_day, buildings=buildings)

                        else:
                            run_timeout = input(">>> Faire une étude de convergence avec la config du main ? [Y/N] > ")
                            # ----------------------------------------------------------------
                            # Branche CONVERGENCE : on lance run_cp_experiment
                            # ----------------------------------------------------------------
                            if run_timeout.lower() in ("y", "yes", ""):
                                input_data = input(">>> Donner le chemin vers le fichier d'instance > ")
                                t = int(input("Timeout en secondes > "))
                                n = int(input("Combien de runs pour faire la moyenne ? > "))
                                print(f"Temps estimé : {n*t//3600}h {(n*t%3600)//60}m {(n*t)%60}s")
                                eid = run_cp_experiment(config, input_data, t=t, n=n)
                                print(f"ID de ce run : {eid}")

                                ans = input(">>> Afficher les courbes de cette expérience ? [Y/N] > ")
                                if ans.lower() in ("yes", "y", ""):
                                    plot_cp_experiment(instance=input_data, t=t, experiment_id=eid)

                            else:
                                affiche_run_timeout = input(">>> Afficher les résultats d'une étude de convergence ? [Y/N] > ")
                                # ----------------------------------------------------------------
                                # Branche AFFICHAGE DE CONVERGENCE : on lance plot_cp_experiment
                                # ----------------------------------------------------------------
                                if affiche_run_timeout.lower() in ("y", "yes", ""):
                                    print("Voici la liste des études de convergence disponibles:")
                                    list_cp_experiments()
                                    inst_filter = input(">>> Filtrer par instance (chemin exact, vide = toutes) > ").strip() or None
                                    t_filter_raw = input(">>> Filtrer par timeout en secondes (vide = tous) > ").strip()
                                    t_filter = int(t_filter_raw) if t_filter_raw else None
                                    eid = input(">>> experiment_id à visualiser (Rien = le plus récent) > ").strip() or None
                                    plot_cp_experiment(instance=inst_filter, t=t_filter, experiment_id=eid)

                                else:
                                    load_ans = input(">>> Charger un EDT existant dans le but de run un scénario ? [Y/N] > ")
                                    # ----------------------------------------------------------------
                                    # Branche SCENARIO : on lance un scénario
                                    # ----------------------------------------------------------------
                                    if load_ans.lower() in ("y", "yes", ""):
                                        edt_name = input(">>> Nom de l'EDT à charger (sans extension) : > ").strip()
                                        edt = load_edt(edt_name)
                                        name = edt_name

                                        log_entry = get_log_entry(edt_name)
                                        if log_entry is None:
                                            raise ValueError(f"Aucune entrée de log pour '{edt_name}' — impossible de récupérer l'instance et les paramètres.")

                                        input_data_scen   = log_entry["input"]
                                        nb_days_scen      = log_entry.get("nb_days",          nb_days)
                                        nb_slots_scen     = log_entry.get("nb_slots_per_day", nb_slots_per_day)
                                        lunch_slots_scen  = log_entry.get("lunch_slots",      lunch_slots)

                                        courses_scen, rooms_scen, _, _buildings_scen, _ = load_input(input_data_scen)
                                        print(f"Instance chargée : {input_data_scen}  "
                                            f"({nb_days_scen}j x {nb_slots_scen} slots, lunch={lunch_slots_scen})")

                                        html_ans = input(">>> Générer le HTML pour visualiser cet EDT ? [Y/N] > ")
                                        if html_ans.lower() in ("y", "yes", ""):
                                            affichage_html_complet(edt, nb_days_scen, courses_scen, rooms_scen,
                                                                name + ".html", lunch_slots_scen, nb_slots_scen)

                                        log_constraints = log_entry.get("constraints", [])
                                        if log_constraints:
                                            soft_scorers = build_soft_scorers(log_constraints)
                                        else:
                                            print(f"[!] Aucune contrainte dans le log pour '{name}' — placement greedy pur.")
                                            soft_scorers = None

                                        print("Scénarios disponibles : [1] Prof absent  [2] Salle indisponible  [0] Aucun")
                                        scenario_ans = input(">>> Choix : > ").strip()

                                        def _parse_slots(prompt):
                                            raw = input(prompt).strip()
                                            if not raw:
                                                return None
                                            return [(int(p.split(",")[0]), int(p.split(",")[1])) for p in raw.split()]

                                        def _apply_scenario(new_schedule, cancelled, suffix):
                                            if cancelled:
                                                print(f"\n{len(cancelled)} cours annulé(s) :")
                                                for c in cancelled:
                                                    print(f"  - Cours {c.course} ({c.group}) jour {c.day} slot {c.slot}")
                                            else:
                                                print("Aucun cours annulé !")
                                            new_name = name + suffix
                                            save_edt(new_schedule, new_name)
                                            print(f"Nouvel EDT sauvegardé : {new_name}.json")
                                            if input("Générer le HTML ? [Y/N] > ").lower() in ("y", "yes", ""):
                                                affichage_html_complet(new_schedule, nb_days_scen, courses_scen, rooms_scen,
                                                                    new_name + ".html", lunch_slots_scen, nb_slots_scen)

                                        if scenario_ans == "1":
                                            tid   = input(">>> ID du prof absent (ex: T1) : > ").strip()
                                            slots = _parse_slots(">>> Créneaux d'absence 'day,slot' séparés par espaces (ex: 0,3 1,5): > ")
                                            new_schedule, cancelled = teacher_absent(
                                                edt, courses_scen, rooms_scen, nb_days_scen, nb_slots_scen,
                                                teacher_id=tid, absent_slots=slots, lunch_slots=lunch_slots_scen,
                                                soft_scorers=soft_scorers,
                                            )
                                            _apply_scenario(new_schedule, cancelled, f"_{tid}_absent")

                                        elif scenario_ans == "2":
                                            rname = input(">>> Nom de la salle indisponible (ex: TD1) : > ").strip()
                                            slots = _parse_slots(
                                                ">>> Créneaux bloqués 'day,slot' (vide = salle retirée définitivement) : > "
                                            )
                                            new_schedule, cancelled = room_unavailable(
                                                edt, courses_scen, rooms_scen, nb_days_scen, nb_slots_scen,
                                                room_name=rname, lunch_slots=lunch_slots_scen, absent_slots=slots,
                                                soft_scorers=soft_scorers,
                                            )
                                            _apply_scenario(new_schedule, cancelled, f"_{rname}_indispo")
                        

    except Exception:
        # On affiche la vraie erreur au lieu de la masquer silencieusement
        import traceback
        traceback.print_exc()