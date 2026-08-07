"""
term_solver.py — Résolution sur un semestre complet (2 niveaux)

Ce module est une SURCOUCHE du solver existant (solver.py).
Il ne modifie pas solver.py — il l'appelle simplement pour chaque semaine.

Architecture :
    term_solve()          ← point d'entrée principal
        └── week_solve()  ← Level 1 : quelle session dans quelle semaine ?
        └── solve()       ← Level 2 : placement dans la grille (solver.py inchangé)

Vocabulaire :
    "session" = une occurrence d'un cours dans une semaine
                ex: le cours Maths_CM a sessions=["CM","CM","TD"]
                    → 3 sessions à placer sur le semestre

    "sessions_map" = dict {course_id → ["CM", "CM", "TD", ...]}
                     passé séparément — Course.session_room_types gère
                     quel type de salle utiliser pour chaque type de session
"""

from ortools.sat.python import cp_model
from typing import List, Dict, Optional, Tuple
from basics import Course, Room, ScheduleItem
from solver import solve


# ===========================================================================
# LEVEL 1 — week_solve
# ===========================================================================

def week_solve(
    courses: List[Course],
    sessions_map: Dict[int, List[str]],
    nb_weeks: int,
    nb_days: int = 5,
    nb_slots_per_day: int = 8,
    max_sessions_per_group_per_week: Optional[int] = None,
    balance_weight: int = 2,
    teacher_unavailable_weeks: Optional[Dict[str, List[int]]] = None,
    order_penalty: int = 30,
    ordering_weight: int = 2,
    timeout: int = 60,
) -> Dict[Tuple[int, int], int]:
    """
    Décide dans quelle semaine chaque session de chaque cours tombe.

    Paramètres
    ----------
    courses : liste des cours du semestre
    sessions_map : dict course_id → liste ordonnée de types de sessions
                   ex: {1: ["CM", "CM", "TD", "CM", "TD", "TP"]}
                   L'ordre dans la liste = l'ordre souhaité par le prof.
    nb_weeks : durée du semestre en semaines
    max_sessions_per_group_per_week : charge max qu'un groupe peut avoir par semaine.
                                      None = auto : ceil(sessions_du_groupe / nb_weeks) + 1
                                      C'est la vraie contrainte d'équilibre — dure, par groupe,
                                      calculée depuis les données. Préférer ça à un balance_weight élevé.
    balance_weight : poids soft de l'écart à la charge moyenne globale.
                     Doit rester comparable à ordering_weight (même ordre de grandeur).
                     L'équilibre réel vient surtout de max_sessions_per_group_per_week.
    teacher_unavailable_weeks : dict teacher_id → liste de semaines indisponibles
                                ex: {"T1": [2, 7, 8]}  (semaines 0-indexées)
    order_penalty : poids de la pénalité si une session est placée
                    après la suivante (violation de l'ordre demandé)
    ordering_weight : poids des pénalités de préférence temporelle
                      (early/late/middle définie sur chaque Course)

    balance_weight : poids de la pénalité d'écart à la charge moyenne.
                     Plus élevé → distribution plus uniforme entre semaines.
                     0 = pas de contrainte de balance.
                     Doit être > ordering_weight pour que l'équilibre prime
                     sur les préférences early/late/middle.

    Retourne
    --------
    dict (course_id, session_index) → numéro de semaine (0-indexé)
    """

    if teacher_unavailable_weeks is None:
        teacher_unavailable_weeks = {}

    # Auto-calcul de max_sessions_per_group_per_week si non fourni.
    # Pour chaque groupe : ceil(nb_sessions_du_groupe / nb_weeks) + 1
    # C'est la borne naturelle : on accepte une session de dépassement par semaine.
    if max_sessions_per_group_per_week is None:
        import math
        sessions_per_group: Dict[str, int] = {}
        for c in courses:
            n = len(sessions_map.get(c.id, []))
            sessions_per_group[c.group] = sessions_per_group.get(c.group, 0) + n
        if sessions_per_group:
            avg_per_group = sum(sessions_per_group.values()) / len(sessions_per_group)
            max_sessions_per_group_per_week = math.ceil(
                (avg_per_group / nb_weeks) * 1.5
            )
        else:
            max_sessions_per_group_per_week = 8

    model = cp_model.CpModel()

    # -----------------------------------------------------------------------
    # VARIABLES
    # week_var[(c.id, i)] = semaine dans laquelle tombe la i-ème session
    #                        du cours c. Domaine : [0, nb_weeks-1].
    # -----------------------------------------------------------------------
    week_var = {}
    for c in courses:
        sessions = sessions_map.get(c.id, [])
        for i in range(len(sessions)):
            week_var[(c.id, i)] = model.NewIntVar(
                0, nb_weeks - 1, f"w_{c.id}_{i}"
            )

    # -----------------------------------------------------------------------
    # INDICATEURS b_at[(c.id, i, w)]
    # BoolVar = 1 si la session i du cours c est assignée à la semaine w.
    # Nécessaires pour exprimer les contraintes de charge par semaine.
    # b_at est lié à week_var par : b=1 <=> week_var==w
    # -----------------------------------------------------------------------
    b_at = {}
    for c in courses:
        sessions = sessions_map.get(c.id, [])
        for i in range(len(sessions)):
            for w in range(nb_weeks):
                b = model.NewBoolVar(f"bat_{c.id}_{i}_{w}")
                model.Add(week_var[(c.id, i)] == w).OnlyEnforceIf(b)
                model.Add(week_var[(c.id, i)] != w).OnlyEnforceIf(b.Not())
                b_at[(c.id, i, w)] = b

    # -----------------------------------------------------------------------
    # BALANCE — charge totale par semaine
    #
    # week_load[w] = nombre total de sessions assignées à la semaine w.
    # avg_load     = charge idéale (total / nb_weeks, arrondi à l'entier).
    #
    # Contrainte souple : pénalise |week_load[w] - avg_load|
    #   → pousse vers une distribution uniforme
    #   → linéarisé avec balance_dev[w] >= ±(week_load - avg)
    #   → poids balance_weight > ordering_weight pour que l'équilibre prime
    # -----------------------------------------------------------------------
    total_sessions_count = sum(
        len(sessions_map.get(c.id, [])) for c in courses
    )
    avg_load = total_sessions_count // nb_weeks

    week_load = {}
    for w in range(nb_weeks):
        indicators_w = [
            b_at[(c.id, i, w)]
            for c in courses
            for i in range(len(sessions_map.get(c.id, [])))
        ]
        if indicators_w:
            wl = model.NewIntVar(0, total_sessions_count, f"wload_{w}")
            model.Add(wl == sum(indicators_w))
            week_load[w] = wl

    # -----------------------------------------------------------------------
    # CONTRAINTE DURE 1 — charge max par groupe par semaine
    # Pour chaque groupe g et chaque semaine w :
    #   somme des sessions assignées à w ≤ max_sessions_per_group_per_week
    # Evite qu'un groupe ait 12 sessions en semaine 1 et 0 en semaine 5.
    # -----------------------------------------------------------------------
    courses_by_group = {}
    for c in courses:
        courses_by_group.setdefault(c.group, []).append(c)

    for g, group_courses in courses_by_group.items():
        for w in range(nb_weeks):
            indicators = [
                b_at[(c.id, i, w)]
                for c in group_courses
                for i in range(len(sessions_map.get(c.id, [])))
            ]
            if indicators:
                model.Add(sum(indicators) <= max_sessions_per_group_per_week)

    # -----------------------------------------------------------------------
    # CONTRAINTE DURE 1b — charge max par enseignant par semaine
    # Pour chaque prof T et chaque semaine w :
    #   somme des sessions de T assignées à w ≤ nb_days × nb_slots_per_day
    #
    # Un prof ne peut enseigner que dans les créneaux disponibles de la semaine.
    # Sans cette contrainte, week_solve peut concentrer toutes les sessions d'un
    # prof chargé (ex: Anglais × 12 groupes) sur une même semaine, ce qui rend
    # la grille horaire infaisable même si la contrainte groupe est respectée.
    # -----------------------------------------------------------------------
    sessions_per_teacher = {}
    for c in courses:
        n = len(sessions_map.get(c.id, []))
        sessions_per_teacher[c.teacher.id] = sessions_per_teacher.get(c.teacher.id, 0) + n

    courses_by_teacher = {}
    for c in courses:
        courses_by_teacher.setdefault(c.teacher.id, []).append(c)

    for t_id, teacher_courses in courses_by_teacher.items():
        max_t = math.ceil(sessions_per_teacher[t_id] / nb_weeks) + 1   # ← borne propre à ce prof
        for w in range(nb_weeks):
            indicators = [
                b_at[(c.id, i, w)]
                for c in teacher_courses
                for i in range(len(sessions_map.get(c.id, [])))
            ]
            if indicators:
                model.Add(sum(indicators) <= max_t)   # ← max_t, pas max_teacher_sessions_per_week

    # -----------------------------------------------------------------------
    # CONTRAINTE DURE 1c — sessions max d'un même cours par semaine
    # Pour chaque cours C et chaque semaine w :
    #   nombre de sessions de C assignées à w ≤ slots_per_week
    #
    # slots_per_week indique combien de fois ce cours doit apparaître par
    # semaine active (ex: 1 = une seule séance par semaine). Assigner plus de
    # sessions à une même semaine n'a pas de sens pédagogique et surcharge à la
    # fois le groupe et l'enseignant.
    # -----------------------------------------------------------------------
    # for c in courses:
    #     spw = getattr(c, "slots_per_week", 1) or 1
    #     sessions = sessions_map.get(c.id, [])
    #     for w in range(nb_weeks):
    #         indicators = [b_at[(c.id, i, w)] for i in range(len(sessions))]
    #         if indicators:
    #             model.Add(sum(indicators) <= spw)

    # -----------------------------------------------------------------------
    # CONTRAINTE DURE 2 — disponibilité des profs
    # Si un prof est indisponible semaine w (congé, déplacement, etc.),
    # aucune de ses sessions ne peut être assignée à cette semaine.
    # -----------------------------------------------------------------------
    for c in courses:
        unavailable = teacher_unavailable_weeks.get(c.teacher.id, [])
        sessions = sessions_map.get(c.id, [])
        for i in range(len(sessions)):
            for w in unavailable:
                # Forcer : cette session NE PEUT PAS tomber semaine w
                model.Add(b_at[(c.id, i, w)] == 0)

    # -----------------------------------------------------------------------
    # CONTRAINTE SOUPLE 1 — respecter l'ordre des sessions
    # Le prof a demandé l'ordre CM CM TD CM TD TP...
    # On souhaite : week_var[(c.id, i)] <= week_var[(c.id, i+1)]
    # Si cette condition est violée (inversion), on pénalise.
    #
    # inv[(c.id, i)] = 1 si la session i est placée APRES la session i+1
    # Chaque violation coûte `order_penalty` dans l'objectif.
    # -----------------------------------------------------------------------
    penalties = []
    for c in courses:
        sessions = sessions_map.get(c.id, [])
        for i in range(len(sessions) - 1):
            inv = model.NewBoolVar(f"inv_{c.id}_{i}")
            model.Add(week_var[(c.id, i)] > week_var[(c.id, i + 1)]).OnlyEnforceIf(inv)
            model.Add(week_var[(c.id, i)] <= week_var[(c.id, i + 1)]).OnlyEnforceIf(inv.Not())
            penalties.append(order_penalty * inv)

    # -----------------------------------------------------------------------
    # CONTRAINTE SOUPLE 2 — préférence de placement sur le semestre
    # Définie par Course.ordering_preference : "early", "late" ou "middle".
    #
    # "early" : on pénalise week_var directement.
    #   Plus une session est placée tard, plus la pénalité est grande.
    #   → minimize sum(week_var[(c.id, i)]) pour les cours "early"
    #
    # "late" : on pénalise (nb_weeks - 1 - week_var).
    #   Plus une session est placée tôt, plus la pénalité est grande.
    #   → minimize sum(nb_weeks - 1 - week_var[(c.id, i)]) pour les cours "late"
    #
    # "middle" : on pénalise l'écart au milieu du semestre.
    #   |week_var - target| n'est pas linéaire → on le linéarise avec une
    #   variable auxiliaire abs_dev >= 0 telle que :
    #     abs_dev >= week_var - target
    #     abs_dev >= target - week_var
    #   Le solver minimisera abs_dev (valeur minimale = |week_var - target|).
    # -----------------------------------------------------------------------
    target = nb_weeks // 2  # milieu du semestre (entier)

    for c in courses:
        pref = c.ordering_preference
        if pref is None:
            continue
        sessions = sessions_map.get(c.id, [])
        for i in range(len(sessions)):
            v = week_var[(c.id, i)]
            if pref == "early":
                # Pénalité = week_var  (min → sessions poussées vers semaine 0)
                penalties.append(ordering_weight * v)

            elif pref == "late":
                # Pénalité = nb_weeks - 1 - week_var  (min → sessions poussées vers la fin)
                # On crée une variable intermédiaire pour exprimer (nb_weeks-1-v)
                late_pen = model.NewIntVar(0, nb_weeks - 1, f"late_{c.id}_{i}")
                model.Add(late_pen == (nb_weeks - 1) - v)
                penalties.append(ordering_weight * late_pen)

            elif pref == "middle":
                # Linéarisation de |week_var - target|
                # abs_dev est une IntVar >= 0 bornée par [0, nb_weeks-1]
                abs_dev = model.NewIntVar(0, nb_weeks - 1, f"absd_{c.id}_{i}")
                model.Add(abs_dev >= v - target)
                model.Add(abs_dev >= target - v)
                penalties.append(ordering_weight * abs_dev)

    # -----------------------------------------------------------------------
    # CONTRAINTE SOUPLE 3 — balance de la charge par semaine
    # Pour chaque semaine w, on pénalise |week_load[w] - avg_load|
    # Linéarisé : balance_dev[w] >= wl - avg  et  >= avg - wl
    # -----------------------------------------------------------------------
    if balance_weight > 0:
        for w, wl in week_load.items():
            bd = model.NewIntVar(0, total_sessions_count, f"bdev_{w}")
            model.Add(bd >= wl - avg_load)
            model.Add(bd >= avg_load - wl)
            penalties.append(balance_weight * bd)

    # Minimiser toutes les pénalités (ordre + préférences temporelles + balance)
    if penalties:
        model.Minimize(sum(penalties))

    # -----------------------------------------------------------------------
    # RÉSOLUTION
    # -----------------------------------------------------------------------
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = timeout

    status = solver.Solve(model)

    if solver.StatusName(status) not in ("OPTIMAL", "FEASIBLE"):
        raise RuntimeError(
            f"week_solve : impossible de trouver une assignation valide "
            f"({solver.StatusName(status)}). "
            f"Essayez d'augmenter max_sessions_per_group_per_week."
        )

    print(f"  → week_solve : {solver.StatusName(status)}, objectif={int(solver.ObjectiveValue())}")
    print(f"     charge/semaine cible≈{avg_load}, max/groupe/semaine={max_sessions_per_group_per_week}")
    # Distribution réelle
    dist = {}
    for c in courses:
        for i in range(len(sessions_map.get(c.id, []))):
            w = solver.Value(week_var[(c.id, i)])
            dist[w] = dist.get(w, 0) + 1
    dist_str = "  ".join(f"S{w+1}:{dist.get(w,0)}" for w in range(nb_weeks))
    print(f"     {dist_str}")

    # Extraire l'assignation finale
    assignment = {}
    for c in courses:
        sessions = sessions_map.get(c.id, [])
        for i in range(len(sessions)):
            assignment[(c.id, i)] = solver.Value(week_var[(c.id, i)])

    ws_meta = {
        "status":    solver.StatusName(status),
        "objective": int(solver.ObjectiveValue()),
    }
    return assignment, ws_meta


# ===========================================================================
# FALLBACK GREEDY — _greedy_week
# ===========================================================================

def _greedy_week(
    temp_courses: List[Course],
    rooms: List[Room],
    nb_days: int,
    nb_slots_per_day: int,
    lunch_slots: List[int],
) -> Tuple[List[ScheduleItem], int]:
    """
    Fallback garanti : place chaque session dans le premier créneau valide.

    Respecte uniquement les contraintes DURES :
      - pas de conflit groupe / prof / salle au même créneau
      - capacité de la salle ≥ headcount du cours
      - au moins 1 slot déjeuner libre par jour pour le groupe et le prof

    Aucune contrainte SOUPLE n'est appliquée (pas de LongLunch, NoGap, etc.).
    Utilisé quand CP-SAT échoue après tous les niveaux de fallback.

    Retourne
    --------
    (schedule, nb_failed)
        schedule   : liste de ScheduleItem placés
        nb_failed  : nombre de sessions non plaçables (conflits hard insurmontables)
    """
    from scenarios import try_place

    new_schedule:   List[ScheduleItem] = []
    failed_courses: List[Course]       = []
    occ_group:   set = set()
    occ_room:    set = set()
    occ_teacher: set = set()

    for tc in temp_courses:
        stub = ScheduleItem(
            course=tc.id,
            group=tc.group,
            teacher=tc.teacher,
            day=0, slot=0, room="",
        )
        placed = try_place(
            item=stub,
            course=tc,
            nb_days=nb_days,
            nb_slots_per_day=nb_slots_per_day,
            rooms=rooms,
            absent_slots=set(),
            lunch_slots=lunch_slots,
            occ_group=occ_group,
            occ_room=occ_room,
            occ_teacher=occ_teacher,
            new_schedule=new_schedule,
            soft_scorers=None,
        )
        if not placed:
            failed_courses.append(tc)

    return new_schedule, failed_courses


# ===========================================================================
# LEVEL 2 — term_solve
# ===========================================================================

def term_solve(
    courses: List[Course],
    rooms: List[Room],
    sessions_map: Dict[int, List[str]],
    nb_weeks: int,
    nb_days: int,
    lunch_slots: Optional[List[int]] = None,
    nb_slots_per_day: int = 10,
    constraints=None,
    timeout: int = 60,
    week_solve_timeout: int = 60,
    buildings=None,
    num_workers: int = 4,
    max_sessions_per_group_per_week: Optional[int] = None,
    balance_weight: int = 2,
    teacher_unavailable_weeks: Optional[Dict[str, List[int]]] = None,
    order_penalty: int = 30,
    ordering_weight: int = 2,
) -> List[Tuple[int, object]]:
    """
    Résout l'emploi du temps sur un semestre complet.

    Étape 1 — week_solve() :
        Assigne chaque session à une semaine (modèle CP-SAT léger).

    Étape 2 — solve() pour chaque semaine :
        Pour chaque semaine, on crée des Course temporaires (slots_per_week=1)
        correspondant aux sessions assignées à cette semaine, puis on appelle
        solve() de solver.py exactement comme en mode semaine unique.
        solver.py ne sait pas qu'il est dans un contexte semestre — il place
        juste les sessions qu'on lui donne dans la grille horaire.

    Paramètres
    ----------
    courses : liste des cours du semestre
    rooms : liste des salles disponibles
    sessions_map : dict course_id → liste ordonnée de types de sessions
    nb_weeks : nombre de semaines du semestre
    nb_days, lunch_slots, nb_slots_per_day : paramètres de la grille horaire
    constraints : liste de contraintes (même format que pour solve())
    timeout : timeout en secondes pour chaque résolution de semaine
    buildings : liste de Building (pour contraintes Closer/CloserTeacher)
    num_workers : nb de threads CPU pour le solver
    max_sessions_per_group_per_week : charge max par groupe par semaine
    teacher_unavailable_weeks : dict teacher_id → semaines indisponibles
    order_penalty : poids de la pénalité pour violation d'ordre dans week_solve

    Retourne
    --------
    list de (week_number, result) où result est soit :
        - None si aucune session cette semaine ou résolution échouée
        - (solver_obj, slot, temp_courses, status, score) sinon
          (même format que ce que retourne solve(), pour pouvoir
           appeler recup_edt() dessus)
    """

    if lunch_slots is None:
        lunch_slots = [2, 3, 4]

    import datetime as _dt
    def _now():
        return _dt.datetime.now().strftime("%H:%M:%S")

    # -----------------------------------------------------------------------
    # ÉTAPE 1 : assigner les sessions aux semaines
    # -----------------------------------------------------------------------
    print(f"\n=== Semestre : {nb_weeks} semaines, {len(courses)} cours ===")
    print("Étape 1 : assignation des sessions aux semaines (week_solve)...")

    assignment, ws_meta = week_solve(
        courses, sessions_map, nb_weeks,
        nb_days=nb_days,
        nb_slots_per_day=nb_slots_per_day,
        max_sessions_per_group_per_week=max_sessions_per_group_per_week,
        balance_weight=balance_weight,
        teacher_unavailable_weeks=teacher_unavailable_weeks,
        order_penalty=order_penalty,
        ordering_weight=ordering_weight,
        timeout=week_solve_timeout,
    )

    total_sessions = len(assignment)
    print(f"  {total_sessions} sessions réparties sur {nb_weeks} semaines.\n")

    # -----------------------------------------------------------------------
    # ÉTAPE 2 : résoudre la grille horaire semaine par semaine
    # -----------------------------------------------------------------------
    print("Étape 2 : résolution de la grille horaire par semaine (solve)...")

    # Index rapide course_id → Course pour retrouver les attributs du cours parent
    course_by_id = {c.id: c for c in courses}

    results = []
    all_unplaced: List[Tuple[int, Course]] = []   # (semaine_0idx, course) non placés par greedy

    for w in range(nb_weeks):

        # Trouver toutes les sessions assignées à cette semaine
        sessions_this_week = [
            (course_by_id[c_id], i)
            for (c_id, i), week in assignment.items()
            if week == w
        ]

        if not sessions_this_week:
            print(f"  [{_now()}] Semaine {w+1:2d}/{nb_weeks} : aucune session.")
            results.append((w, None))
            continue

        # -------------------------------------------------------------------
        # Créer des Course temporaires pour cette semaine.
        #
        # Pourquoi ?
        # solve() attend une liste de Course avec slots_per_week.
        # Or ici chaque session est indépendante (une seule occurrence
        # à placer dans la grille). On crée donc un Course par session,
        # avec slots_per_week=1, en conservant tous les autres attributs
        # du cours parent (group, teacher, headcount, room_types).
        #
        # L'id est rendu unique avec "_w{w}_s{i}" pour éviter les conflits
        # entre sessions de cours différents qui auraient des ids proches.
        # -------------------------------------------------------------------
        temp_courses = []
        for c, i in sessions_this_week:
            session_type = sessions_map.get(c.id, [])[i] if sessions_map.get(c.id) else None

            # Choisir les room_types selon le type de session.
            # Si course.session_room_types est défini et contient ce type,
            # on l'utilise — sinon on retombe sur room_types du cours parent.
            # Ex: session_type="CM", session_room_types={"CM":["CM"],"TD":["TD"]}
            #     → room_types=["CM"] pour cette session.
            if session_type and c.session_room_types and session_type in c.session_room_types:
                rt = c.session_room_types[session_type]
            else:
                rt = c.room_types

            temp_c = Course(
                id=f"{c.id}_w{w}_s{i}",  # id unique pour cette session précise
                name=f"{c.name} ({session_type}) S{w+1}",
                teacher=c.teacher,
                group=c.group,
                headcount=c.headcount,
                room_types=rt,             # room_types adapté au type de session
                slots_per_week=1,          # une seule session à placer cette semaine
            )
            temp_courses.append(temp_c)

        print(f"  [{_now()}] Semaine {w+1:2d}/{nb_weeks} : {len(temp_courses):3d} sessions...", end=" ", flush=True)

        try:
            # -------------------------------------------------------------------
            # Niveau 1 : solve() avec toutes les contraintes
            # -------------------------------------------------------------------
            s_obj, s_slot, _, _, s_stat, s_score, _, _ = solve(
                temp_courses, rooms, nb_days,
                lunch_slots=lunch_slots,
                nb_slots_per_day=nb_slots_per_day,
                constraints=constraints,
                timeout=timeout,
                buildings=buildings,
                num_workers=num_workers,
            )
            print(s_stat, end="", flush=True)

            final_solver, final_slot   = s_obj, s_slot
            final_status, final_score  = s_stat, s_score
            fallback_edt               = None

            if final_status not in ("OPTIMAL", "FEASIBLE"):

                # ---------------------------------------------------------------
                # Niveau 2 : retry sans contraintes soft (utile si UNKNOWN)
                # INFEASIBLE = conflit hard → pas la peine de retenter sans softs
                # ---------------------------------------------------------------
                if final_status == "UNKNOWN":
                    t2 = max(timeout // 2, 15)
                    print(f"  → [F2] sans softs ({t2}s)...", end=" ", flush=True)
                    s2_obj, s2_slot, _, _, s2_stat, s2_score, _, _ = solve(
                        temp_courses, rooms, nb_days,
                        lunch_slots=lunch_slots,
                        nb_slots_per_day=nb_slots_per_day,
                        constraints=[],
                        timeout=t2,
                        buildings=buildings,
                        num_workers=num_workers,
                    )
                    print(s2_stat, end="", flush=True)
                    if s2_stat in ("OPTIMAL", "FEASIBLE"):
                        final_solver, final_slot  = s2_obj, s2_slot
                        final_status, final_score = s2_stat, s2_score

                # ---------------------------------------------------------------
                # Niveau 3 : greedy fallback garanti
                # ---------------------------------------------------------------
                if final_status not in ("OPTIMAL", "FEASIBLE"):
                    print(f"  → [F3] greedy...", end=" ", flush=True)
                    greedy_sched, failed_courses = _greedy_week(
                        temp_courses, rooms, nb_days, nb_slots_per_day, lunch_slots
                    )
                    fallback_edt = greedy_sched
                    final_status = "GREEDY"
                    final_score  = 0.0
                    n_failed  = len(failed_courses)
                    n_placed  = len(temp_courses) - n_failed
                    warn = f"  ⚠ {n_failed} non plaçable(s)" if n_failed else ""
                    print(f"GREEDY ({n_placed}/{len(temp_courses)}){warn}", end="")
                    for fc in failed_courses:
                        all_unplaced.append((w, fc))

            print(f"  (score={final_score})" if final_status != "GREEDY" else "")

            results.append((w, (final_solver, final_slot, temp_courses,
                                final_status, final_score, fallback_edt)))

        except Exception as e:
            print(f"ÉCHEC : {e}")
            results.append((w, None))

    # Résumé
    solved   = sum(1 for _, r in results if r is not None)
    optimal  = sum(1 for _, r in results if r is not None and r[3] == "OPTIMAL")
    feasible = sum(1 for _, r in results if r is not None and r[3] == "FEASIBLE")
    greedy   = sum(1 for _, r in results if r is not None and r[3] == "GREEDY")
    print(f"\nRésumé : {solved}/{nb_weeks} semaines résolues "
          f"({optimal} OPTIMAL, {feasible} FEASIBLE, {greedy} GREEDY fallback)")

    if all_unplaced:
        print(f"\n⚠  {len(all_unplaced)} session(s) non placées par le greedy (conflits hard insolubles) :")
        # Grouper par semaine pour la lisibilité
        from collections import defaultdict as _dd
        by_week = _dd(list)
        for w_idx, fc in all_unplaced:
            by_week[w_idx].append(fc)
        for w_idx in sorted(by_week):
            print(f"  Semaine {w_idx+1:2d} ({len(by_week[w_idx])} session(s)) :")
            for fc in by_week[w_idx]:
                # fc.id est du type "3_w2_s0" en mode semestre — on affiche le nom lisible
                print(f"      {fc.name:<35}  groupe={fc.group:<6}  prof={fc.teacher.id}")
    else:
        print("\nToutes les sessions ont été placées (aucune perte greedy).")

    return results, ws_meta, all_unplaced
