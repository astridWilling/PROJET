from ortools.sat.python import cp_model
from typing import List
from basics import *
from greedy import build_occupations, _expand_groups, _group_conflict, greedy_fallback, greedy_fallback_with_blocked
from analyze_scenarios import analyze_free_slot, analyze_teacher_absent, analyze_room_unavailable, analyze_teacher_replacement
from scorers import remaining_hours
import basics # pour pouvoir faire basics.MIN_DAY



class BestSolutionCallback(cp_model.CpSolverSolutionCallback):
    """
    Enregistre chaque nouvelle meilleure solution trouvée : (wall_time_s, objective).
    Utilisé pour tracer la courbe de convergence score vs temps.
    """
    def __init__(self):
        super().__init__()
        self._solutions = []

    def on_solution_callback(self):
        self._solutions.append((self.WallTime(), self.ObjectiveValue()))

    @property
    def solutions(self):
        return self._solutions

def _best_slot(candidates, day):
    """Picker automatique : retourne toujours le meilleur candidat (index 0)."""
    return 0 if candidates else None

def collect_absent_intervals(list_perturb: List[dict], group_list: List["Group"], rooms_list: List["Room"], nb_days: int):
    """
    Crée un dict de listes d'intervalle d'absence par entité (prof, salle, groupe) à partir de la liste de perturbations.

    Retourne : {
        "teacher": {teacher_id: [(day, start, end), ...], ...},
        "room":    {room_name: [(day, start, end), ...], ...},
        "group":   {group_id: [(day, start, end), ...], ...},
    }
    """
    absent_intervals={
        "teachers": {},
        "rooms": {},
        "groups": {}
    }
    for perturb in list_perturb:
        if perturb["type"] == 1:
            tid = perturb["teacher_id"]
            if tid not in absent_intervals["teachers"]:
                absent_intervals["teachers"][tid] = perturb["intervals"]
            else:
                absent_intervals["teachers"][tid].extend(perturb["intervals"])
        elif perturb["type"] == 2:
            if perturb["room"] is None:
                for r in rooms_list:
                    rname = r.name if hasattr(r, "name") else r
                    if perturb["intervals"]==None:
                        perturb["intervals"] = [(i,"00h00","23h59") for i in range(nb_days)]
                    if rname not in absent_intervals["rooms"]:
                        absent_intervals["rooms"][rname] = list(perturb["intervals"])
                    else:
                        absent_intervals["rooms"][rname].extend(perturb["intervals"])
            else:
                rname = perturb["room"]
                if perturb["intervals"]==None:
                    perturb["intervals"] = [(i,"00h00","23h59") for i in range(nb_days)]
                if rname not in absent_intervals["rooms"]:
                    absent_intervals["rooms"][rname] = list(perturb["intervals"])
                else:
                    absent_intervals["rooms"][rname].extend(perturb["intervals"])
        elif perturb["type"] == 3:
            grp = perturb["groups"] if perturb["groups"] is not None else [g.id for g in group_list]
            for g in grp:
                gid = g.id if hasattr(g, "id") else g
                if gid not in absent_intervals["groups"]:
                    absent_intervals["groups"][gid] = list(perturb["intervals"])
                else:
                    absent_intervals["groups"][gid].extend(perturb["intervals"])
        else:
            continue
    return absent_intervals

############################################################################################################
############################# CASCADE ######################################################################
############################################################################################################
#*##########################################################
#* Solve pour une perturbation de type 1,2,3 (CP-SAT)
#*##########################################################
def solve_perturbation(
    to_reschedule:    List[ScheduleItem],
    fixed_schedule:   List[ScheduleItem],
    courses:          List[Course],
    rooms:            List[Room],
    nb_days:          int,
    valid_starts:     List[int],          # minutes depuis minuit
    absent_intervals: "AbsentIntervals",
    lunch_debut_min:  int,
    lunch_fin_min:    int,
    global_absent:    dict = None,
    soft_scorers:     "Optional[ScorerList]" = None,
    timeout:          int = 60,
    num_workers:      int = 4,
    min_day:          int = 0,
    locked_slots:     "Optional[dict]" = None,
) -> Tuple[Optional[List[ScheduleItem]], List[ScheduleItem], str]:
    """
    Tente de replanifier tous les cours de to_reschedule simultanément
    en CP-SAT.

    Retourne (new_schedule, cancelled, status_name) :
      - new_schedule : fixed_schedule + cours replacés (None si échec)
      - cancelled    : cours non placés
      - status_name  : "OPTIMAL", "FEASIBLE", "INFEASIBLE", "UNKNOWN", ...
    """
    course_map = {c.id: c for c in courses}
    course_map.update({str(c.id): c for c in courses})

    # Occupation des cours fixes (conflits potentiels avec les cours perturbés)
    group_day_index, occ_room, occ_teacher = build_occupations(fixed_schedule)

    # Occupation fixe dans la fenêtre midi, par (entité, jour)
    lunch_fixed_group:   dict = defaultdict(int)   # (group, day)      -> min occupées
    lunch_fixed_teacher: dict = defaultdict(int)   # (teacher_id, day) -> min occupées
    for item in fixed_schedule:
        t1, t2 = hm(item.heure_debut), hm(item.heure_fin)
        ov = max(0, min(t2, lunch_fin_min) - max(t1, lunch_debut_min))
        if ov > 0:
            for g in item.group:
                lunch_fixed_group[(g.id, item.day)]           += ov
            lunch_fixed_teacher[(item.teacher.id, item.day)]  += ov

    model = cp_model.CpModel()

    # ------------------------------------------------------------------
    # Énumération des placements valides et création des variables
    # ------------------------------------------------------------------
    X               = {}
    valid_placements = defaultdict(list)  # c_id -> [(d, start_min, r_name), ...]

    nb_blocked_teacher = {}
    nb_blocked_group = {}
    nb_blocked_room = {}

    for item in to_reschedule:
        c_key = base_course_id(item.course)
        c     = course_map.get(c_key) or course_map.get(str(c_key))
        if c is None:
            continue
        dur = hm(item.heure_fin) - hm(item.heure_debut)
        locked_slot = (locked_slots or {}).get(id(item))

        nb_blocked_teacher[id(item)] = 0
        nb_blocked_group[id(item)] = 0
        nb_blocked_room[id(item)] = 0

        for d in range(min_day, nb_days):
            if locked_slot is not None and d != locked_slot[0]:
                continue
            for start_min in valid_starts:
                if locked_slot is not None and min_to_hm(start_min) != locked_slot[1]:
                    continue
                end_min = start_min + dur

                # Absent intervals
                blocked = False
                for (ad, ah_debut, ah_fin) in absent_intervals:
                    if ad == d and start_min < hm(ah_fin) and hm(ah_debut) < end_min:
                        blocked = True
                        break
                if blocked:
                    continue

                # Lunch constraint — basée sur occupation fixe uniquement
                lunch_ov = max(0, min(end_min, lunch_fin_min) - max(start_min, lunch_debut_min))
                if lunch_ov > 0:
                    lw    = lunch_fin_min - lunch_debut_min
                    g_occ = max((lunch_fixed_group.get((g.id, d), 0) for g in item.group), default=0)
                    t_occ = lunch_fixed_teacher.get((c.teacher.id, d), 0)
                    if (lw - g_occ - lunch_ov) < LUNCH_MIN_FREE_MINUTES:
                        continue
                    if (lw - t_occ - lunch_ov) < LUNCH_MIN_FREE_MINUTES:
                        continue

                for r in rooms:
                    # Type et capacité
                    if r.capacity < sum(g.headcount for g in item.group):
                        continue
                    # session_type (CSV) donne le type de CETTE séance ; c.room_types liste TOUS les types du cours.
                    # Si session_type est générique (ex: "TP") et c.room_types contient un sous-type plus précis
                    # (ex: "TP_SI"), on utilise le sous-type. Sinon on garde session_type tel quel.
                    if item.session_type:
                        specific = [rt for rt in c.room_types if rt.startswith(item.session_type) and rt != item.session_type]
                        req = specific if specific else [item.session_type]
                    else:
                        req = c.room_types
                    if req and not any(rt in r.room_types for rt in req):
                        continue

                    # Conflit avec cours fixes — groupe via bisect O(log n)
                    if any(_group_conflict(gid, d, start_min, end_min, group_day_index)
                           for gid in _expand_groups(item.group)):
                        continue
                    conflict = any(
                        (r.name,       d, m) in occ_room or
                        (c.teacher.id, d, m) in occ_teacher
                        for m in range(start_min, end_min)
                    )
                    if conflict:
                        continue

                    blocked = False
                    for (abd, abh, abf) in (global_absent or {}).get("teachers", {}).get(item.teacher.id, []):
                        if abd == d and start_min < hm(abf) and hm(abh) < end_min:
                            blocked = True; nb_blocked_teacher[id(item)] += 1; break
                    if not blocked:
                        for g in item.group:
                            for (abd, abh, abf) in (global_absent or {}).get("groups", {}).get(g.id, []):
                                if abd == d and start_min < hm(abf) and hm(abh) < end_min:
                                    blocked = True; nb_blocked_group[id(item)] += 1; break
                            if blocked: break
                    if not blocked:
                        for (abd, abh, abf) in (global_absent or {}).get("rooms", {}).get(r.name, []):
                            if abd == d and start_min < hm(abf) and hm(abh) < end_min:
                                blocked = True; nb_blocked_room[id(item)] += 1; break
                    if blocked:
                        continue

                    key = (item.course, d, start_min, r.name)
                    X[key] = model.NewBoolVar(f"x_{item.course}_{d}_{start_min}_{r.name}")
                    valid_placements[item.course].append((d, start_min, r.name))

    # ------------------------------------------------------------------
    # Contrainte 1 — chaque cours placé exactement une fois
    # (les cours sans placement valide sont directement annulés)
    # ------------------------------------------------------------------
    placed_items:    List[ScheduleItem] = []
    cancelled_items: List[ScheduleItem] = []

    for item in to_reschedule:
        placements = valid_placements[item.course]
        if not placements:
            c_key = base_course_id(item.course)
            c     = course_map.get(c_key) or course_map.get(str(c_key))
            cname = c.name if c else str(item.course)
            types = c.room_types if c else "?"
            reason = []
            if nb_blocked_teacher.get(id(item), 0) > 0 : reason.append(f"Aucun créneau avec un professeur disponible")
            if nb_blocked_group.get(id(item), 0) > 0 : reason.append(f"Aucun créneau où le groupe est disponible")
            if nb_blocked_room.get(id(item), 0) > 0 : reason.append(f"Aucun créneau avec une salle disponible")
            print(f"  [!] Aucun placement valide pour {item.course} {', '.join([g.id for g in item.group])} ({fmt_abs_day(item.day)}, {item.heure_debut}-{item.heure_fin} — {', '.join(reason) if reason else 'contraintes planning'}")

            cancelled_items.append(item)
            continue
        placed_items.append(item)
        model.AddExactlyOne(X[(item.course, d, s, r)] for (d, s, r) in placements)

    # ------------------------------------------------------------------
    # Contrainte 2 — pas de chevauchement via IntervalVar + AddNoOverlap
    # ------------------------------------------------------------------
    group_ivs   = defaultdict(list)   # (group, day)      -> [IntervalVar]
    teacher_ivs = defaultdict(list)   # (teacher_id, day) -> [IntervalVar]
    room_ivs    = defaultdict(list)   # (room_name, day)  -> [IntervalVar]

    # Les conflits fixes ↔ perturbés sont gérés par le pré-filtrage (valid_placements).
    # On n'ajoute PAS d'intervalles fixes dans le modèle : si le planning original
    # a des chevauchements légitimes (ex. amphi : même prof, deux groupes, même heure),
    # des intervalles fixes provoqueraient un INFEASIBLE immédiat dans AddNoOverlap.
    # Les AddNoOverlap ci-dessous gèrent uniquement les conflits perturbé ↔ perturbé.

    # Intervalles OPTIONNELS (cours perturbés — actifs ssi X=1)
    for item in placed_items:
        c_key = base_course_id(item.course)
        c     = course_map.get(c_key) or course_map.get(str(c_key))
        dur   = hm(item.heure_fin) - hm(item.heure_debut)

        for (d, start_min, r_name) in valid_placements[item.course]:
            end_min = start_min + dur
            bv = X[(item.course, d, start_min, r_name)]
            sfx = f"{item.course}_{d}_{start_min}"

            for gid in _expand_groups(item.group):
                group_ivs[(gid, d)].append(
                    model.NewOptionalIntervalVar(start_min, dur, end_min, bv, f"iv_g_{sfx}_{gid}"))
            teacher_ivs[(c.teacher.id, d)].append(
                model.NewOptionalIntervalVar(start_min, dur, end_min, bv, f"iv_t_{sfx}"))
            room_ivs[(r_name, d)].append(
                model.NewOptionalIntervalVar(start_min, dur, end_min, bv, f"iv_r_{sfx}_{r_name}"))

    # AddNoOverlap par entité-jour (gère fixes ↔ perturbés et perturbés ↔ perturbés)
    for ivs in group_ivs.values():
        if len(ivs) > 1:
            model.AddNoOverlap(ivs)
    for ivs in teacher_ivs.values():
        if len(ivs) > 1:
            model.AddNoOverlap(ivs)
    for ivs in room_ivs.values():
        if len(ivs) > 1:
            model.AddNoOverlap(ivs)

    # ------------------------------------------------------------------
    # Objectif soft — minimize ∑ penalty × X
    # (pénalités calculées sur l'occupation fixe uniquement)
    # ------------------------------------------------------------------
    scorers   = soft_scorers or []
    penalties = []
    room_map  = {r.name: r for r in rooms}   # aussi utilisé à la reconstruction

    if scorers:
        for item in placed_items:
            c_key = base_course_id(item.course)
            c     = course_map.get(c_key) or course_map.get(str(c_key))
            dur   = hm(item.heure_fin) - hm(item.heure_debut)
            for (d, start_min, r_name) in valid_placements[item.course]:
                r = room_map.get(r_name)
                if r is None:
                    continue
                hd = min_to_hm(start_min)
                hf = min_to_hm(start_min + dur)
                soft_pen = sum(
                    w * fn(item, c, d, hd, hf, r,
                           group_day_index, occ_teacher, lunch_debut_min, lunch_fin_min)
                    for fn, w in scorers
                )
                if soft_pen != 0:
                    pen_int = int(round(soft_pen * 100))
                    penalties.append(pen_int * X[(item.course, d, start_min, r_name)])

    if penalties:
        model.Minimize(sum(penalties))

    # ------------------------------------------------------------------
    # Résolution
    # ------------------------------------------------------------------
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = timeout
    solver.parameters.num_search_workers  = num_workers

    cb     = BestSolutionCallback()
    status = solver.Solve(model, cb)
    status_name = solver.StatusName(status)

    if status_name not in ("OPTIMAL", "FEASIBLE"):
        return None, to_reschedule, status_name

    # ------------------------------------------------------------------
    # Reconstruction du planning résolu
    # ------------------------------------------------------------------
    new_schedule = list(fixed_schedule)

    for item in placed_items:
        dur = hm(item.heure_fin) - hm(item.heure_debut)
        placed = False
        for (d, start_min, r_name) in valid_placements[item.course]:
            if solver.Value(X[(item.course, d, start_min, r_name)]) == 1:
                r_obj    = room_map.get(r_name)
                new_item = item._replace(
                    day=d,
                    heure_debut=min_to_hm(start_min),
                    heure_fin=min_to_hm(start_min + dur),
                    room=r_name,
                    building=r_obj.bat if r_obj else item.building,
                )
                new_schedule.append(new_item)
                placed = True
                break
        if not placed:
            cancelled_items.append(item)

    # Si des cours ont été annulés (pré-filtrage ou post-solve), le statut
    # "OPTIMAL" du solveur est trompeur — on le dégrade en "PARTIAL".
    final_status = status_name if not cancelled_items else (
        "PARTIAL" if status_name in ("OPTIMAL", "FEASIBLE") else status_name
    )
    return new_schedule, cancelled_items, final_status


#?####################################################################
#? Solve pour une perturbation de type 1,2,3 (CP-SAT+Greedy fallback)
#?####################################################################
def resolve(
    to_reschedule:    List[ScheduleItem],
    fixed_schedule:   List[ScheduleItem],
    courses:          List[Course],
    rooms:            List[Room],
    nb_days:          int,
    valid_starts:     List[int],
    absent_intervals: AbsentIntervals,
    lunch_debut_min:  int,
    lunch_fin_min:    int,
    global_absent:    dict = None,
    soft_scorers:     Optional[ScorerList] = None,
    solver_timeout:   int = 60,
    min_day:          int = 0,
    locked_slots:     Optional[dict] = None,
) -> Tuple[List[ScheduleItem], List[ScheduleItem], str, List[ScheduleItem]]:
    """
    Tente CP-SAT en premier.  Si le solveur échoue, repasse sur le greedy.
    Retourne (new_schedule, cancelled, status, rescheduled).
    rescheduled = items effectivement replacés avec leur nouvelle position.
    locked_slots = {id(item): (day, heure_debut)} pour forcer jour ET créneau.
    """
    if not to_reschedule:
        return list(fixed_schedule), [], "OPTIMAL", []

    n_fixed = len(fixed_schedule)

    try:
        new_sched, cancelled, status = solve_perturbation(
            to_reschedule=to_reschedule,
            fixed_schedule=fixed_schedule,
            courses=courses,
            rooms=rooms,
            nb_days=nb_days,
            valid_starts=valid_starts,
            absent_intervals=absent_intervals,
            lunch_debut_min=lunch_debut_min,
            lunch_fin_min=lunch_fin_min,
            global_absent=global_absent,
            soft_scorers=soft_scorers,
            timeout=solver_timeout,
            min_day=min_day,
            locked_slots=locked_slots,
        )
    except Exception as e:
        print(f"  → CP-SAT : EXCEPTION ({type(e).__name__}: {e}) — fallback greedy.")
        status = f"EXCEPTION:{type(e).__name__}"
        new_sched, cancelled = None, to_reschedule

    if status in ("OPTIMAL", "FEASIBLE", "PARTIAL"):
        print(f"  → CP-SAT : {status} — {len(cancelled)} cours non placé(s).")
        return new_sched, cancelled, status, new_sched[n_fixed:]

    print(f"  → CP-SAT : {status} — fallback greedy.")
    #* Etait juste un greedy_fallback, mais on a utilisé with_blocked car ca permet de ne pas rajouter global_absent dans greedy_fallback
    new_sched, cancelled, rescheduled = greedy_fallback_with_blocked(
        to_reschedule=to_reschedule,
        fixed_schedule=fixed_schedule,
        courses=courses,
        rooms=rooms,
        nb_days=nb_days,
        valid_starts=valid_starts,
        absent_intervals=absent_intervals,
        lunch_debut_min=lunch_debut_min,
        lunch_fin_min=lunch_fin_min,
        teacher_blocked=(global_absent or {}).get("teachers", {}),
        rooms_blocked=(global_absent or {}).get("rooms", {}),
        groups_blocked=(global_absent or {}).get("groups", {}),
        soft_scorers=soft_scorers,
        min_day=min_day,
        locked_slots=locked_slots,
    )
    return new_sched, cancelled, "GREEDY", rescheduled


############################################################################################################
############################# SCENARIOS 4,5,6 ##############################################################
############################################################################################################
#*##########################################################
#* Solve pour un remplacement (CP-SAT)
#*##########################################################
def find_candidates(
    instance:        ScheduleItem,
    course:          Course,
    fixed_schedule:  List[ScheduleItem],
    teachers:        List[Teacher],
    teachers_blocked: dict = None,
    verbose:         bool = False,
) -> List[Tuple["Teacher", float]]:
    """
    Pour une instance de cours, retourne les profs candidats triés par adéquation.

    Filtres appliqués :
      1. Département : le prof doit être dans le même dept que le cours
         (ignoré si course.dept ou teacher.dept est None)
      2. Compétence : le cours doit être dans possible_classes du prof
         (ignoré si possible_classes est None → le prof peut tout faire)
      3. Quota : le prof a encore des heures disponibles
      4. Disponibilité : le prof est libre à ce créneau dans le planning fixe

    Retourne : [(teacher, adequacy_score), ...] trié par score décroissant.
    Si verbose=True, affiche pourquoi chaque prof est exclu.
    """
    t1, t2 = hm(instance.heure_debut), hm(instance.heure_fin)
    dur_h  = (t2 - t1) / 60.0

    def _is_busy(day: int, hd: int, hf: int, list_intervals: List[Tuple[int, str, str]]) -> bool:
        if list_intervals is None:
            return False
        else:
            for (d, h_debut, h_fin) in list_intervals:
                if d == day and hd < hm(h_fin) and hm(h_debut) < hf:
                    return True
            return False

    # Occupation minute-par-minute des profs dans le planning fixe
    busy_teachers: Set[str] = set()
    for item in fixed_schedule:
        it1, it2 = hm(item.heure_debut), hm(item.heure_fin)
        if item.day == instance.day and it1 < t2 and t1 < it2:
            busy_teachers.add(item.teacher.id)
        
    candidates = []
    for teacher in teachers:
        # 1. Ne pas proposer le prof absent lui-même
        if teacher.id == instance.teacher.id:
            continue

        # 2. Filtre département
        if course.dept and teacher.dept and course.dept != teacher.dept:
            if verbose:
                print(f"      → {teacher.name} : dept {teacher.dept} ≠ {course.dept}")
            continue

        # 3. Filtre compétence + score d'adéquation
        if teacher.possible_classes is not None:
            adequacy = teacher.possible_classes.get(course.id)
            if adequacy is None:
                adequacy = teacher.possible_classes.get(str(course.id))
            if adequacy is None:
                if verbose:
                    print(f"      → {teacher.name} : pas compétent pour '{course.name}'")
                continue   # ne sait pas enseigner ce cours
        else:
            adequacy = 0.5  # pas d'info → adéquation neutre

        # 4. Filtre quota
        rem = remaining_hours(teacher, fixed_schedule)
        if rem < dur_h:
            if verbose:
                print(f"      → {teacher.name} : quota épuisé ({rem:.2f}h restantes < {dur_h:.2f}h)")
            continue

        # 5. Filtre disponibilité
        if _is_busy(instance.day, t1, t2, teachers_blocked.get(teacher.id, [])):    # Si le prof est absent à ce créneau
            if verbose:
                print(f"      → {teacher.name} : occupé à ce créneau")
            continue
        if teacher.id in busy_teachers:                                             # Si le prof  a deja cours à ce créneau
            if verbose:
                print(f"      → {teacher.name} : occupé à ce créneau")
            continue

        candidates.append((teacher, float(adequacy)))

    candidates.sort(key=lambda x: x[1], reverse=True)
    return candidates


def solve_replacement(
    affected:       List[ScheduleItem],
    candidates:     List[List[Tuple["Teacher", float]]],  # candidates[i] pour affected[i]
    fixed_schedule: List[ScheduleItem],
    timeout:        int = 30,
) -> Tuple[dict, str]:
    """
    CP-SAT : assigne un prof remplaçant à chaque instance en maximisant l'adéquation.

    Variables : Y[i, t_id] ∈ {0,1} — le prof t remplace l'instance i.

    Contraintes :
      - Chaque instance reçoit au plus un remplaçant (on tolère "non résolu")
      - Un prof ne peut pas couvrir deux instances qui se chevauchent
      - Le quota d'heures de chaque prof n'est pas dépassé

    Objectif : maximiser Σ adequacy * Y[i, t_id]

    Retourne : {instance_idx: (teacher, adequacy)}, status_name
    """

    model  = cp_model.CpModel()
    Y: dict = {}

    for i, cands in enumerate(candidates):
        for teacher, _ in cands:
            Y[(i, teacher.id)] = model.NewBoolVar(f"y_{i}_{teacher.id}")

    # Chaque instance : au plus un remplaçant
    for i, cands in enumerate(candidates):
        vars_i = [Y[(i, t.id)] for t, _ in cands]
        if vars_i:
            model.AddAtMostOne(vars_i)

    # Un prof ne double-booke pas deux instances qui se chevauchent
    teacher_to_idxs: dict = defaultdict(list)
    for i, cands in enumerate(candidates):
        for teacher, _ in cands:
            teacher_to_idxs[teacher.id].append(i)

    for t_id, idxs in teacher_to_idxs.items():
        for a in range(len(idxs)):
            for b in range(a + 1, len(idxs)):
                ia, ib = idxs[a], idxs[b]
                inst_a, inst_b = affected[ia], affected[ib]
                if inst_a.day == inst_b.day:
                    t1a, t2a = hm(inst_a.heure_debut), hm(inst_a.heure_fin)
                    t1b, t2b = hm(inst_b.heure_debut), hm(inst_b.heure_fin)
                    if t1a < t2b and t1b < t2a and (ia, t_id) in Y and (ib, t_id) in Y:
                        model.AddAtMostOne([Y[(ia, t_id)], Y[(ib, t_id)]])

    # Quota : les heures assignées ne dépassent pas le reste disponible
    all_tids = {t.id for cands in candidates for t, _ in cands}
    teacher_map = {t.id: t for cands in candidates for t, _ in cands}

    for t_id in all_tids:
        teacher = teacher_map[t_id]
        rem     = remaining_hours(teacher, fixed_schedule)
        if rem == float("inf"):
            continue
        rem_min = int(rem * 60)
        terms   = []
        for i, inst in enumerate(affected):
            if (i, t_id) in Y:
                dur = hm(inst.heure_fin) - hm(inst.heure_debut)
                terms.append(dur * Y[(i, t_id)])
        if terms:
            model.Add(sum(terms) <= rem_min)

    # Objectif : maximiser l'adéquation (scores * 100 pour entiers)
    obj = []
    for i, cands in enumerate(candidates):
        for teacher, adequacy in cands:
            if (i, teacher.id) in Y:
                obj.append(int(adequacy * 100) * Y[(i, teacher.id)])
    if obj:
        model.Maximize(sum(obj))

    solver      = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = timeout
    status      = solver.Solve(model)
    status_name = solver.StatusName(status)

    if status_name not in ("OPTIMAL", "FEASIBLE"):
        return {}, status_name

    assignment = {}
    for i, cands in enumerate(candidates):
        for teacher, adequacy in cands:
            if (i, teacher.id) in Y and solver.Value(Y[(i, teacher.id)]) == 1:
                assignment[i] = (teacher, adequacy)
                break

    return assignment, status_name

#*##########################################################
#* Solve pour des déplacement (CP-SAT)
#*##########################################################
def solve_move_all(
    to_move:          List[Tuple[ScheduleItem, int, Optional[str]]],
    fixed_schedule:   List[ScheduleItem],
    courses:          List[Course],
    rooms:            List[Room],
    nb_days:          int,
    valid_starts:     List[int],          # minutes depuis minuit
    lunch_debut_min:  int,
    lunch_fin_min:    int,
    global_absent:    dict = None,
    soft_scorers:     "Optional[ScorerList]" = None,
    timeout:          int = 60,
    num_workers:      int = 4,
) -> Tuple[List[ScheduleItem], List[ScheduleItem], List[ScheduleItem], str]:
    """
    Tente de déplacer les cours tel que demandé dans to_move

    Retourne (new_schedule, cancelled, status_name) :
      - new_schedule : fixed_schedule + cours replacés (None si échec)
      - cancelled    : cours non placés
      - moved_items  : cours déplacés
      - status_name  : "OPTIMAL", "FEASIBLE", "INFEASIBLE", "UNKNOWN", ...
    """
    course_map = {c.id: c for c in courses}
    course_map.update({str(c.id): c for c in courses})

    # Occupation des cours fixes (conflits potentiels avec les cours perturbés)
    group_day_index, occ_room, occ_teacher = build_occupations(fixed_schedule)

    # Occupation fixe dans la fenêtre midi, par (entité, jour)
    lunch_fixed_group:   dict = defaultdict(int)   # (group, day)      -> min occupées
    lunch_fixed_teacher: dict = defaultdict(int)   # (teacher_id, day) -> min occupées
    for item in fixed_schedule:
        t1, t2 = hm(item.heure_debut), hm(item.heure_fin)
        ov = max(0, min(t2, lunch_fin_min) - max(t1, lunch_debut_min))
        if ov > 0:
            for g in item.group:
                lunch_fixed_group[(g.id, item.day)]           += ov
            lunch_fixed_teacher[(item.teacher.id, item.day)]  += ov

    model = cp_model.CpModel()

    # ------------------------------------------------------------------
    # Énumération des placements valides et création des variables
    # ------------------------------------------------------------------
    X               = {}
    valid_placements = defaultdict(list)  # c_id -> [(d, start_min, r_name), ...]

    nb_blocked_teacher = {}
    nb_blocked_group = {}
    nb_blocked_room = {}

    for item, target_day, heure_debut in to_move:

        nb_blocked_teacher[id(item)] = 0
        nb_blocked_group[id(item)] = 0
        nb_blocked_room[id(item)] = 0


        c_key = base_course_id(item.course)
        c     = course_map.get(c_key) or course_map.get(str(c_key))
        if c is None:
            continue
        dur = hm(item.heure_fin) - hm(item.heure_debut)

        for d in range(nb_days):
            if d!=target_day:  # On regarde que le jour cible pour chaque cours à déplacer
                continue
            for start_min in valid_starts:
                if heure_debut and start_min != hm(heure_debut): # Si heure_debut donnée, on ne regarde que si c'est possible ou non
                    continue

                end_min = start_min + dur

                # Lunch constraint — basée sur occupation fixe uniquement
                lunch_ov = max(0, min(end_min, lunch_fin_min) - max(start_min, lunch_debut_min))
                if lunch_ov > 0:
                    lw    = lunch_fin_min - lunch_debut_min
                    g_occ = max((lunch_fixed_group.get((g.id, d), 0) for g in item.group), default=0)
                    t_occ = lunch_fixed_teacher.get((c.teacher.id, d), 0)
                    if (lw - g_occ - lunch_ov) < LUNCH_MIN_FREE_MINUTES:
                        continue
                    if (lw - t_occ - lunch_ov) < LUNCH_MIN_FREE_MINUTES:
                        continue

                for r in rooms:
                    # Type et capacité
                    if r.capacity < sum(g.headcount for g in item.group):
                        continue
                    # session_type (CSV) donne le type de CETTE séance ; c.room_types liste TOUS les types du cours.
                    # Si session_type est générique (ex: "TP") et c.room_types contient un sous-type plus précis
                    # (ex: "TP_SI"), on utilise le sous-type. Sinon on garde session_type tel quel.
                    if item.session_type:
                        specific = [rt for rt in c.room_types if rt.startswith(item.session_type) and rt != item.session_type]
                        req = specific if specific else [item.session_type]
                    else:
                        req = c.room_types
                    if req and not any(rt in r.room_types for rt in req):
                        continue

                    # Conflit avec cours fixes — groupe via bisect O(log n)
                    if any(_group_conflict(gid, d, start_min, end_min, group_day_index)
                           for gid in _expand_groups(item.group)):
                        continue
                    conflict = any(
                        (r.name,       d, m) in occ_room or
                        (c.teacher.id, d, m) in occ_teacher
                        for m in range(start_min, end_min)
                    )
                    if conflict:
                        continue

                    blocked = False
                    for (abd, abh, abf) in (global_absent or {}).get("teachers", {}).get(item.teacher.id, []):
                        if abd == d and start_min < hm(abf) and hm(abh) < end_min:
                            blocked = True; nb_blocked_teacher[id(item)] += 1; break
                    if not blocked:
                        for g in item.group:
                            for (abd, abh, abf) in (global_absent or {}).get("groups", {}).get(g.id, []):
                                if abd == d and start_min < hm(abf) and hm(abh) < end_min:
                                    blocked = True; nb_blocked_group[id(item)] += 1; break
                            if blocked: break
                    if not blocked:
                        for (abd, abh, abf) in (global_absent or {}).get("rooms", {}).get(r.name, []):
                            if abd == d and start_min < hm(abf) and hm(abh) < end_min:
                                blocked = True; nb_blocked_room[id(item)] += 1; break
                    if blocked:
                        continue

                    key = (item.course, d, start_min, r.name)
                    X[key] = model.NewBoolVar(f"x_{item.course}_{d}_{start_min}_{r.name}")
                    valid_placements[item.course].append((d, start_min, r.name))

    # ------------------------------------------------------------------
    # Contrainte 1 — chaque cours placé exactement une fois
    # (les cours sans placement valide sont directement annulés)
    # ------------------------------------------------------------------
    placed_items:    List[ScheduleItem] = []
    cancelled_items: List[ScheduleItem] = []

    for item, target_day, heure_debut in to_move:
        placements = valid_placements[item.course]
        if not placements:
            c_key = base_course_id(item.course)
            c     = course_map.get(c_key) or course_map.get(str(c_key))
            cname = c.name if c else str(item.course)
            types = c.room_types if c else "?"
            reason = []
            if nb_blocked_teacher.get(id(item), 0) > 0 : reason.append(f"Aucun créneau avec un professeur disponible")
            if nb_blocked_group.get(id(item), 0) > 0 : reason.append(f"Aucun créneau où le groupe est disponible")
            if nb_blocked_room.get(id(item), 0) > 0 : reason.append(f"Aucun créneau avec une salle disponible")
            print(f"  [!] Aucun placement valide pour {item.course} {', '.join([g.id for g in item.group])} ({fmt_abs_day(item.day)}, {item.heure_debut}-{item.heure_fin} — {', '.join(reason) if reason else 'contraintes planning'}")
            cancelled_items.append(item)
            continue
        placed_items.append(item)
        model.AddExactlyOne(X[(item.course, d, s, r)] for (d, s, r) in placements)

    # ------------------------------------------------------------------
    # Contrainte 2 — pas de chevauchement via IntervalVar + AddNoOverlap
    # ------------------------------------------------------------------
    group_ivs   = defaultdict(list)   # (group, day)      -> [IntervalVar]
    teacher_ivs = defaultdict(list)   # (teacher_id, day) -> [IntervalVar]
    room_ivs    = defaultdict(list)   # (room_name, day)  -> [IntervalVar]

    # Les conflits fixes ↔ perturbés sont gérés par le pré-filtrage (valid_placements).
    # On n'ajoute PAS d'intervalles fixes dans le modèle : si le planning original
    # a des chevauchements légitimes (ex. amphi : même prof, deux groupes, même heure),
    # des intervalles fixes provoqueraient un INFEASIBLE immédiat dans AddNoOverlap.
    # Les AddNoOverlap ci-dessous gèrent uniquement les conflits perturbé ↔ perturbé.

    # Intervalles OPTIONNELS (cours perturbés — actifs ssi X=1)
    for item in placed_items:
        c_key = base_course_id(item.course)
        c     = course_map.get(c_key) or course_map.get(str(c_key))
        dur   = hm(item.heure_fin) - hm(item.heure_debut)

        for (d, start_min, r_name) in valid_placements[item.course]:
            end_min = start_min + dur
            bv = X[(item.course, d, start_min, r_name)]
            sfx = f"{item.course}_{d}_{start_min}"

            for gid in _expand_groups(item.group):
                group_ivs[(gid, d)].append(
                    model.NewOptionalIntervalVar(start_min, dur, end_min, bv, f"iv_g_{sfx}_{gid}"))
            teacher_ivs[(c.teacher.id, d)].append(
                model.NewOptionalIntervalVar(start_min, dur, end_min, bv, f"iv_t_{sfx}"))
            room_ivs[(r_name, d)].append(
                model.NewOptionalIntervalVar(start_min, dur, end_min, bv, f"iv_r_{sfx}_{r_name}"))

    # AddNoOverlap par entité-jour (gère fixes ↔ perturbés et perturbés ↔ perturbés)
    for ivs in group_ivs.values():
        if len(ivs) > 1:
            model.AddNoOverlap(ivs)
    for ivs in teacher_ivs.values():
        if len(ivs) > 1:
            model.AddNoOverlap(ivs)
    for ivs in room_ivs.values():
        if len(ivs) > 1:
            model.AddNoOverlap(ivs)

    # ------------------------------------------------------------------
    # Objectif soft — minimize ∑ penalty × X
    # (pénalités calculées sur l'occupation fixe uniquement)
    # ------------------------------------------------------------------
    scorers   = soft_scorers or []
    penalties = []
    room_map  = {r.name: r for r in rooms}   # aussi utilisé à la reconstruction

    if scorers:
        for item in placed_items:
            c_key = base_course_id(item.course)
            c     = course_map.get(c_key) or course_map.get(str(c_key))
            dur   = hm(item.heure_fin) - hm(item.heure_debut)
            for (d, start_min, r_name) in valid_placements[item.course]:
                r = room_map.get(r_name)
                if r is None:
                    continue
                hd = min_to_hm(start_min)
                hf = min_to_hm(start_min + dur)
                soft_pen = sum(
                    w * fn(item, c, d, hd, hf, r,
                           group_day_index, occ_teacher, lunch_debut_min, lunch_fin_min)
                    for fn, w in scorers
                )
                if soft_pen != 0:
                    pen_int = int(round(soft_pen * 100))
                    penalties.append(pen_int * X[(item.course, d, start_min, r_name)])

    if penalties:
        model.Minimize(sum(penalties))

    # ------------------------------------------------------------------
    # Résolution
    # ------------------------------------------------------------------
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = timeout
    solver.parameters.num_search_workers  = num_workers

    cb     = BestSolutionCallback()
    status = solver.Solve(model, cb)
    status_name = solver.StatusName(status)

    if status_name not in ("OPTIMAL", "FEASIBLE"):
        return None, to_move, [], status_name

    # ------------------------------------------------------------------
    # Reconstruction du planning résolu
    # ------------------------------------------------------------------
    new_schedule = list(fixed_schedule)
    moved_items  = []

    for item in placed_items:
        dur = hm(item.heure_fin) - hm(item.heure_debut)
        placed = False
        for (d, start_min, r_name) in valid_placements[item.course]:
            if solver.Value(X[(item.course, d, start_min, r_name)]) == 1:
                r_obj    = room_map.get(r_name)
                new_item = item._replace(
                    day=d,
                    heure_debut=min_to_hm(start_min),
                    heure_fin=min_to_hm(start_min + dur),
                    room=r_name,
                    building=r_obj.bat if r_obj else item.building,
                )
                new_schedule.append(new_item)
                moved_items.append(new_item)
                placed = True
                break
        if not placed:
            cancelled_items.append(item)

    final_status = status_name
    return new_schedule, cancelled_items, moved_items, final_status


#*##########################################################
#* Solve pour des changements de salle (CP-SAT)
#*##########################################################
def solve_all_room_change(
    to_change:        List[ScheduleItem],
    fixed_schedule:   List[ScheduleItem],
    courses:          List[Course],
    rooms:            List[Room],
    lunch_debut_min:  int,
    lunch_fin_min:    int,
    global_absent:    dict = None,
    soft_scorers:     "Optional[ScorerList]" = None,
    timeout:          int = 60,
    num_workers:      int = 4,
) -> Tuple[List[ScheduleItem], List[ScheduleItem], List[ScheduleItem], str]:
    """
    Tente de déplacer les cours tel que demandé dans to_move

    Retourne (new_schedule, cancelled, status_name) :
      - new_schedule : fixed_schedule + cours replacés (None si échec)
      - cancelled    : cours non placés
      - moved_itmes  : cours déplacés dans une autre salle
      - status_name  : "OPTIMAL", "FEASIBLE", "INFEASIBLE", "UNKNOWN", ...
    """
    course_map = {c.id: c for c in courses}
    course_map.update({str(c.id): c for c in courses})

    # Occupation des cours fixes (conflits potentiels avec les cours perturbés)
    group_day_index, occ_room, occ_teacher = build_occupations(fixed_schedule)

    model = cp_model.CpModel()

    # ------------------------------------------------------------------
    # Énumération des placements valides et création des variables
    # ------------------------------------------------------------------
    X               = {}
    valid_placements = defaultdict(list)  # c_id -> [(d, start_min, r_name), ...]

    nb_blocked_teacher = {}
    nb_blocked_group = {}
    nb_blocked_room = {}

    for item in to_change:

        nb_blocked_teacher[id(item)] = 0
        nb_blocked_group[id(item)] = 0
        nb_blocked_room[id(item)] = 0

        c_key = base_course_id(item.course)
        c     = course_map.get(c_key) or course_map.get(str(c_key))
        if c is None:
            continue

        d         = item.day
        start_min = hm(item.heure_debut)
        end_min   = hm(item.heure_fin)

        for r in rooms:
            # Type et capacité
            if r.capacity < sum(g.headcount for g in item.group):
                continue
            # session_type (CSV) donne le type de CETTE séance ; c.room_types liste TOUS les types du cours.
            # Si session_type est générique (ex: "TP") et c.room_types contient un sous-type plus précis
            # (ex: "TP_SI"), on utilise le sous-type. Sinon on garde session_type tel quel.
            if item.session_type:
                specific = [rt for rt in c.room_types if rt.startswith(item.session_type) and rt != item.session_type]
                req = specific if specific else [item.session_type]
            else:
                req = c.room_types

            if req and not any(rt in r.room_types for rt in req):
                continue

            # Conflit avec cours fixes — groupe via bisect O(log n)
            if any(_group_conflict(gid, d, start_min, end_min, group_day_index)
                            for gid in _expand_groups(item.group)):
                continue
            conflict = any(
                        (r.name,       d, m) in occ_room or
                        (c.teacher.id, d, m) in occ_teacher
                        for m in range(start_min, end_min)
                    )
            if conflict:
                continue

            blocked = False
            for (abd, abh, abf) in (global_absent or {}).get("teachers", {}).get(item.teacher.id, []):
                if abd == d and start_min < hm(abf) and hm(abh) < end_min:
                    blocked = True; nb_blocked_teacher[id(item)] += 1; break
            if not blocked:
                for g in item.group:
                    for (abd, abh, abf) in (global_absent or {}).get("groups", {}).get(g.id, []):
                        if abd == d and start_min < hm(abf) and hm(abh) < end_min:
                            blocked = True; nb_blocked_group[id(item)] += 1; break
                    if blocked: break
            if not blocked:
                for (abd, abh, abf) in (global_absent or {}).get("rooms", {}).get(r.name, []):
                    if abd == d and start_min < hm(abf) and hm(abh) < end_min:
                        blocked = True; nb_blocked_room[id(item)] +=1; break
            if blocked:
                continue

            key = (item.course, d, start_min, r.name)
            X[key] = model.NewBoolVar(f"x_{item.course}_{d}_{start_min}_{r.name}")
            valid_placements[item.course].append((d, start_min, r.name))

    # ------------------------------------------------------------------
    # Contrainte 1 — chaque cours placé exactement une fois
    # (les cours sans placement valide sont directement annulés)
    # ------------------------------------------------------------------
    placed_items:    List[ScheduleItem] = []
    cancelled_items: List[ScheduleItem] = []

    for item in to_change:
        placements = valid_placements[item.course]
        if not placements:
            c_key = base_course_id(item.course)
            c     = course_map.get(c_key) or course_map.get(str(c_key))
            cname = c.name if c else str(item.course)
            types = c.room_types if c else "?"
            reason = []
            if nb_blocked_teacher.get(id(item),0) > 0 : reason.append(f"Aucun créneau avec un professeur disponible")
            if nb_blocked_group.get(id(item),0) > 0 : reason.append(f"Aucun créneau où le groupe est disponible")
            if nb_blocked_room.get(id(item),0) > 0 : reason.append(f"Aucun créneau avec une salle disponible")
            print(f"  [!] Aucun placement valide pour {item.course} {', '.join([g.id for g in item.group])} ({fmt_abs_day(item.day)}, {item.heure_debut}-{item.heure_fin} — {', '.join(reason) if reason else 'contraintes planning'}")
            cancelled_items.append(item)
            continue
        placed_items.append(item)
        model.AddExactlyOne(X[(item.course, d, s, r)] for (d, s, r) in placements)

    # ------------------------------------------------------------------
    # Contrainte 2 — pas de chevauchement via IntervalVar + AddNoOverlap
    # ------------------------------------------------------------------
    group_ivs   = defaultdict(list)   # (group, day)      -> [IntervalVar]
    teacher_ivs = defaultdict(list)   # (teacher_id, day) -> [IntervalVar]
    room_ivs    = defaultdict(list)   # (room_name, day)  -> [IntervalVar]

    # Les conflits fixes ↔ perturbés sont gérés par le pré-filtrage (valid_placements).
    # On n'ajoute PAS d'intervalles fixes dans le modèle : si le planning original
    # a des chevauchements légitimes (ex. amphi : même prof, deux groupes, même heure),
    # des intervalles fixes provoqueraient un INFEASIBLE immédiat dans AddNoOverlap.
    # Les AddNoOverlap ci-dessous gèrent uniquement les conflits perturbé ↔ perturbé.

    # Intervalles OPTIONNELS (cours perturbés — actifs ssi X=1)
    for item in placed_items:
        c_key = base_course_id(item.course)
        c     = course_map.get(c_key) or course_map.get(str(c_key))
        dur   = hm(item.heure_fin) - hm(item.heure_debut)

        for (d, start_min, r_name) in valid_placements[item.course]:
            end_min = start_min + dur
            bv = X[(item.course, d, start_min, r_name)]
            sfx = f"{item.course}_{d}_{start_min}"

            for gid in _expand_groups(item.group):
                group_ivs[(gid, d)].append(
                    model.NewOptionalIntervalVar(start_min, dur, end_min, bv, f"iv_g_{sfx}_{gid}"))
            teacher_ivs[(c.teacher.id, d)].append(
                model.NewOptionalIntervalVar(start_min, dur, end_min, bv, f"iv_t_{sfx}"))
            room_ivs[(r_name, d)].append(
                model.NewOptionalIntervalVar(start_min, dur, end_min, bv, f"iv_r_{sfx}_{r_name}"))

    # AddNoOverlap par entité-jour (gère fixes ↔ perturbés et perturbés ↔ perturbés)
    for ivs in group_ivs.values():
        if len(ivs) > 1:
            model.AddNoOverlap(ivs)
    for ivs in teacher_ivs.values():
        if len(ivs) > 1:
            model.AddNoOverlap(ivs)
    for ivs in room_ivs.values():
        if len(ivs) > 1:
            model.AddNoOverlap(ivs)

    # ------------------------------------------------------------------
    # Objectif soft — minimize ∑ penalty × X
    # (pénalités calculées sur l'occupation fixe uniquement)
    # ------------------------------------------------------------------
    scorers   = soft_scorers or []
    penalties = []
    room_map  = {r.name: r for r in rooms}   # aussi utilisé à la reconstruction

    if scorers:
        for item in placed_items:
            c_key = base_course_id(item.course)
            c     = course_map.get(c_key) or course_map.get(str(c_key))
            dur   = hm(item.heure_fin) - hm(item.heure_debut)
            for (d, start_min, r_name) in valid_placements[item.course]:
                r = room_map.get(r_name)
                if r is None:
                    continue
                hd = min_to_hm(start_min)
                hf = min_to_hm(start_min + dur)
                soft_pen = sum(
                    w * fn(item, c, d, hd, hf, r,
                           group_day_index, occ_teacher, lunch_debut_min, lunch_fin_min)
                    for fn, w in scorers
                )
                if soft_pen != 0:
                    pen_int = int(round(soft_pen * 100))
                    penalties.append(pen_int * X[(item.course, d, start_min, r_name)])

    if penalties:
        model.Minimize(sum(penalties))

    # ------------------------------------------------------------------
    # Résolution
    # ------------------------------------------------------------------
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = timeout
    solver.parameters.num_search_workers  = num_workers

    cb     = BestSolutionCallback()
    status = solver.Solve(model, cb)
    status_name = solver.StatusName(status)

    if status_name not in ("OPTIMAL", "FEASIBLE"):
        return None, to_change, [], status_name

    # ------------------------------------------------------------------
    # Reconstruction du planning résolu
    # ------------------------------------------------------------------
    new_schedule = list(fixed_schedule)
    moved_items  = []

    for item in placed_items:
        dur = hm(item.heure_fin) - hm(item.heure_debut)
        placed = False
        for (d, start_min, r_name) in valid_placements[item.course]:
            if solver.Value(X[(item.course, d, start_min, r_name)]) == 1:
                r_obj    = room_map.get(r_name)
                new_item = item._replace(
                    day=d,
                    heure_debut=min_to_hm(start_min),
                    heure_fin=min_to_hm(start_min + dur),
                    room=r_name,
                    building=r_obj.bat if r_obj else item.building,
                )
                new_schedule.append(new_item)
                moved_items.append(new_item)
                placed = True
                break
        if not placed:
            cancelled_items.append(item)

    final_status = status_name
    return new_schedule, cancelled_items, moved_items, final_status

#*##########################################################
#* Solve pour des ajouts de sessions (CP-SAT)
#*##########################################################
def solve_all_add_sessions(
    to_place:         List[Tuple[ScheduleItem, int, dict]],
    schedule:         List[ScheduleItem],
    courses:          List[Course],
    rooms:            List[Room],
    nb_days:          int,
    valid_starts:     List[int],
    lunch_debut_min:  int,
    lunch_fin_min:    int,
    global_absent:    dict = {},
    soft_scorers:     "Optional[ScorerList]" = None,
    timeout:          int = 60,
    num_workers:      int = 4,
) -> Tuple[List[ScheduleItem], List[ScheduleItem], List[ScheduleItem], str]:
    """
    [!] A COMPLETER
    """
    course_map = {c.id: c for c in courses}
    course_map.update({str(c.id): c for c in courses})

    # Occupation des cours fixes (conflits potentiels avec les cours perturbés)
    group_day_index, occ_room, occ_teacher = build_occupations(schedule)

    model = cp_model.CpModel()

    # ------------------------------------------------------------------
    # Énumération des placements valides et création des variables
    # ------------------------------------------------------------------
    X               = {}
    valid_placements = defaultdict(list)  # id(c) -> [(d, start_min, r_name), ...]

    # --- Raisons possibles de l'échec de l'ajout
    reason_teach = {}

    for item, duration, locked_info in to_place:
        c_key = base_course_id(item.course)
        c     = course_map.get(c_key) or course_map.get(str(c_key))
        if c is None:
            continue

        teacher = item.teacher
        course = course_map[item.course]

        # Filtre quota
        dur_h = duration / 60.0
        rem = remaining_hours(teacher, schedule)
        if rem < dur_h:
            reason_teach[id(item)]= f"\n\t→ {teacher.name} : quota épuisé ({rem:.2f}h restantes < {dur_h:.2f}h)"
            continue

        # Filtre compétence + score d'adéquation
        if teacher.possible_classes is not None:
            adequacy = teacher.possible_classes.get(course.id)
            if adequacy is None:
                adequacy = teacher.possible_classes.get(str(course.id))
            if adequacy is None:
                reason_teach[id(item)]= f"\n\t→ {teacher.name} : pas compétent pour '{course.name}'"
                continue   # ne sait pas enseigner ce cours
        else:
            adequacy = 0.5  # pas d'info → adéquation neutre

        

        # Pré-filtrer les espaces de recherche
        if locked_info["days"] is not None:
            days_range = [locked_info["days"]]
        elif locked_info["weeks"] is not None:
            days_range = locked_info["weeks"]
        else:
            days_range = range(basics.MIN_DAY, nb_days)
        days_range = [d for d in days_range if d >= basics.MIN_DAY]

        rooms_range = [locked_info["room"]] if locked_info["room"] is not None else rooms
        starts_range = [hm(locked_info["hd"])] if locked_info["hd"] is not None else valid_starts

        for d in days_range:
            for r in rooms_range:
                for start_min in starts_range:
                    end_min = start_min+duration
                    # Type et capacité
                    if r.capacity < sum(g.headcount for g in item.group):
                        continue
                    # session_type (CSV) donne le type de CETTE séance ; c.room_types liste TOUS les types du cours.
                    # Si session_type est générique (ex: "TP") et c.room_types contient un sous-type plus précis
                    # (ex: "TP_SI"), on utilise le sous-type. Sinon on garde session_type tel quel.
                    if item.session_type:
                        specific = [rt for rt in c.room_types if rt.startswith(item.session_type) and rt != item.session_type]
                        req = specific if specific else [item.session_type]
                    else:
                        req = c.room_types

                    if req and not any(rt in r.room_types for rt in req):
                        continue

                    # Conflit avec cours fixes — groupe via bisect O(log n)
                    if any(_group_conflict(gid, d, start_min, end_min, group_day_index)
                                    for gid in _expand_groups(item.group)):
                        continue
                    conflict = any(
                                (r.name,       d, m) in occ_room or
                                (c.teacher.id, d, m) in occ_teacher
                                for m in range(start_min, end_min)
                            )
                    if conflict:
                        continue

                    blocked = False
                    for (abd, abh, abf) in (global_absent or {}).get("teachers", {}).get(item.teacher.id, []):
                        if abd == d and start_min < hm(abf) and hm(abh) < end_min:
                            blocked = True; break
                    if not blocked:
                        for g in item.group:
                            for (abd, abh, abf) in (global_absent or {}).get("groups", {}).get(g.id, []):
                                if abd == d and start_min < hm(abf) and hm(abh) < end_min:
                                    blocked = True; break
                            if blocked: break
                    if not blocked:
                        for (abd, abh, abf) in (global_absent or {}).get("rooms", {}).get(r.name, []):
                            if abd == d and start_min < hm(abf) and hm(abh) < end_min:
                                blocked = True; break
                    if blocked:
                        continue

                    key = (id(item), d, start_min, r.name)
                    X[key] = model.NewBoolVar(f"x_{item.course}_{d}_{start_min}_{r.name}")
                    valid_placements[id(item)].append((d, start_min, r.name))

    # ------------------------------------------------------------------
    # Contrainte 1 — chaque cours placé exactement une fois
    # (les cours sans placement valide sont directement annulés)
    # ------------------------------------------------------------------
    placed_items:    List[ScheduleItem] = []
    cancelled_items: List[ScheduleItem] = []

    for item, duration, locked_info in to_place:
        placements = valid_placements[id(item)]
        if not placements:
            c_key = base_course_id(item.course)
            c     = course_map.get(c_key) or course_map.get(str(c_key))
            cname = c.name if c else str(item.course)
            types = item.session_type if c else "?"
            day_str = fmt_abs_day(item.day) if item.day is not None else "Meilleur jour possible"

            # --- Raison pour le non placement --- #
            reasons = []

            # Prof absent ?
            if item.teacher:
                days = locked_info.get("weeks") or ([locked_info["days"]] if locked_info.get("days") is not None else range(nb_days))
                for d in days:
                    for (abd, abh, abf) in (global_absent or {}).get("teachers", {}).get(item.teacher.id, []):
                        if abd == d:
                            reasons.append(f"prof {item.teacher.id} absent")
                            break
                    if reasons: break

            # Groupes absents ?
            if not reasons:
                days = locked_info.get("weeks") or ([locked_info["days"]] if locked_info.get("days") is not None else range(nb_days))
                for g in item.group:
                    for d in days:
                        for (abd, abh, abf) in (global_absent or {}).get("groups", {}).get(g.id, []):
                            if abd == d:
                                reasons.append(f"groupe {g.id} indisponible")
                                break

            # Salle demandée incompatible/indispo ?
            if locked_info.get("room"):
                r = locked_info["room"]
                rname = r.name if hasattr(r, "name") else r
                for (abd, abh, abf) in (global_absent or {}).get("rooms", {}).get(rname, []):
                    reasons.append(f"salle {rname} indisponible")
                    break
                if not any("salle" in r for r in reasons):
                    reasons.append(f"salle {rname} incompatible (type/capacité)")

            # Problème de prof (adéquation ou quota d'heures) ?
            res = reason_teach.get(id(item),None)
            if res is not None:
                reasons.append(res)

            # Si le cours est à placer dans le passé
            if locked_info["days"] is not None:
                days_range = [locked_info["days"]]
            elif locked_info["weeks"] is not None:
                days_range = locked_info["weeks"]
            else:
                days_range = range(basics.MIN_DAY, nb_days)
            days_range = [d for d in days_range if d >= basics.MIN_DAY]
            if days_range == []:
                reasons.append("date demandée est déjà passée")

            reason = ", ".join(reasons) if reasons else "aucun créneau valide (conflit planning)"
            print(f"  [!] Aucun placement valide pour '{cname}' ({[g.id for g in item.group]}, {day_str}) (types={types}) : {reason}")
            cancelled_items.append(item)
            continue
        placed_items.append(item)
        model.AddExactlyOne(X[(id(item), d, s, r)] for (d, s, r) in placements)

    # ------------------------------------------------------------------
    # Contrainte 2 — pas de chevauchement via IntervalVar + AddNoOverlap
    # ------------------------------------------------------------------
    group_ivs   = defaultdict(list)   # (group, day)      -> [IntervalVar]
    teacher_ivs = defaultdict(list)   # (teacher_id, day) -> [IntervalVar]
    room_ivs    = defaultdict(list)   # (room_name, day)  -> [IntervalVar]

    # Les conflits fixes ↔ perturbés sont gérés par le pré-filtrage (valid_placements).
    # On n'ajoute PAS d'intervalles fixes dans le modèle : si le planning original
    # a des chevauchements légitimes (ex. amphi : même prof, deux groupes, même heure),
    # des intervalles fixes provoqueraient un INFEASIBLE immédiat dans AddNoOverlap.
    # Les AddNoOverlap ci-dessous gèrent uniquement les conflits perturbé ↔ perturbé.

    # Intervalles OPTIONNELS (cours perturbés — actifs ssi X=1)
    dur_map = {id(item): duration for item, duration, _ in to_place}
    for item in placed_items:
        c_key = base_course_id(item.course)
        c     = course_map.get(c_key) or course_map.get(str(c_key))
        dur   = dur_map[id(item)]

        for (d, start_min, r_name) in valid_placements[id(item)]:
            end_min = start_min + dur
            bv = X[(id(item), d, start_min, r_name)]
            sfx = f"{item.course}_{d}_{start_min}"

            for gid in _expand_groups(item.group):
                group_ivs[(gid, d)].append(
                    model.NewOptionalIntervalVar(start_min, dur, end_min, bv, f"iv_g_{sfx}_{gid}"))
            teacher_ivs[(c.teacher.id, d)].append(
                model.NewOptionalIntervalVar(start_min, dur, end_min, bv, f"iv_t_{sfx}"))
            room_ivs[(r_name, d)].append(
                model.NewOptionalIntervalVar(start_min, dur, end_min, bv, f"iv_r_{sfx}_{r_name}"))

    # AddNoOverlap par entité-jour (gère fixes ↔ perturbés et perturbés ↔ perturbés)
    for ivs in group_ivs.values():
        if len(ivs) > 1:
            model.AddNoOverlap(ivs)
    for ivs in teacher_ivs.values():
        if len(ivs) > 1:
            model.AddNoOverlap(ivs)
    for ivs in room_ivs.values():
        if len(ivs) > 1:
            model.AddNoOverlap(ivs)

    # ------------------------------------------------------------------
    # Objectif soft — minimize ∑ penalty × X
    # (pénalités calculées sur l'occupation fixe uniquement)
    # ------------------------------------------------------------------
    scorers   = soft_scorers or []
    penalties = []
    room_map  = {r.name: r for r in rooms}   # aussi utilisé à la reconstruction

    if scorers:
        for item in placed_items:
            if item.day is None:
                continue  # pas de position d'origine → scorers positionnels inapplicables
            c_key = base_course_id(item.course)
            c     = course_map.get(c_key) or course_map.get(str(c_key))
            dur   = dur_map[id(item)]
            for (d, start_min, r_name) in valid_placements[id(item)]:
                r = room_map.get(r_name)
                if r is None:
                    continue
                hd = min_to_hm(start_min)
                hf = min_to_hm(start_min + dur)
                soft_pen = sum(
                    w * fn(item, c, d, hd, hf, r,
                           group_day_index, occ_teacher, lunch_debut_min, lunch_fin_min)
                    for fn, w in scorers
                )
                if soft_pen != 0:
                    pen_int = int(round(soft_pen * 100))
                    penalties.append(pen_int * X[(id(item), d, start_min, r_name)])

    if penalties:
        model.Minimize(sum(penalties))

    # ------------------------------------------------------------------
    # Résolution
    # ------------------------------------------------------------------
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = timeout
    solver.parameters.num_search_workers  = num_workers

    cb     = BestSolutionCallback()
    status = solver.Solve(model, cb)
    status_name = solver.StatusName(status)

    if status_name not in ("OPTIMAL", "FEASIBLE"):
        return None, [it for it,_,_ in to_place], [], status_name

    # ------------------------------------------------------------------
    # Reconstruction du planning résolu
    # ------------------------------------------------------------------
    new_schedule = list(schedule)
    moved_items  = []

    for item in placed_items:
        dur = dur_map[id(item)]
        placed = False
        for (d, start_min, r_name) in valid_placements[id(item)]:
            if solver.Value(X[(id(item), d, start_min, r_name)]) == 1:
                r_obj    = room_map.get(r_name)
                new_item = item._replace(
                    day=d,
                    heure_debut=min_to_hm(start_min),
                    heure_fin=min_to_hm(start_min + dur),
                    room=r_name,
                    building=r_obj.bat if r_obj else item.building,
                )
                new_schedule.append(new_item)
                moved_items.append(new_item)
                placed = True
                break
        if not placed:
            cancelled_items.append(item)

    final_status = status_name
    return new_schedule, cancelled_items, moved_items, final_status


############################################################################################################
############################# UNE PASSE ####################################################################
############################################################################################################
#*###########################################################
#* Solve pour toutes les perturbation de type 1,2,3 (CP-SAT)
#*###########################################################
def solve_all_perturbations(
    to_reschedule:    List[ScheduleItem],
    fixed_schedule:   List[ScheduleItem],
    courses:          List[Course],
    rooms:            List[Room],
    nb_days:          int,
    valid_starts:     List[int],          # minutes depuis minuit
    absent_intervals: AbsentIntervals,
    teacher_blocked:  dict,  # teacher_id -> [(day, h_debut, h_fin), ...]
    groups_blocked:    dict,  # group_id   -> [(day, h_debut, h_fin), ...]
    rooms_blocked:     dict,  # room_name  -> [(day, h_debut, h_fin), ...]
    lunch_debut_min:  int,
    lunch_fin_min:    int,
    soft_scorers:     "Optional[ScorerList]" = None,
    timeout:          int = 60,
    num_workers:      int = 4,
    min_day:          int = 0,
    locked_slots:     "Optional[dict]" = None,
) -> Tuple[Optional[List[ScheduleItem]], List[ScheduleItem], str]:
    """
    Tente de replanifier tous les cours de to_reschedule simultanément
    en CP-SAT.

    Retourne (new_schedule, cancelled, status_name) :
      - new_schedule : fixed_schedule + cours replacés (None si échec)
      - cancelled    : cours non placés
      - status_name  : "OPTIMAL", "FEASIBLE", "INFEASIBLE", "UNKNOWN", ...
    locked_slots = {id(item): (day, heure_debut)} pour forcer jour ET créneau (type 2).
    """
    course_map = {c.id: c for c in courses}
    course_map.update({str(c.id): c for c in courses})

    # Occupation des cours fixes (conflits potentiels avec les cours perturbés)
    group_day_index, occ_room, occ_teacher = build_occupations(fixed_schedule)

    # Occupation fixe dans la fenêtre midi, par (entité, jour)
    lunch_fixed_group:   dict = defaultdict(int)   # (group, day)      -> min occupées
    lunch_fixed_teacher: dict = defaultdict(int)   # (teacher_id, day) -> min occupées
    for item in fixed_schedule:
        t1, t2 = hm(item.heure_debut), hm(item.heure_fin)
        ov = max(0, min(t2, lunch_fin_min) - max(t1, lunch_debut_min))
        if ov > 0:
            for g in item.group:
                lunch_fixed_group[(g.id, item.day)]           += ov
            lunch_fixed_teacher[(item.teacher.id, item.day)]  += ov

    model = cp_model.CpModel()

    # ------------------------------------------------------------------
    # Énumération des placements valides et création des variables
    # Clé par item = (item.course, idx) pour distinguer deux items ayant
    # le même course_id (ex. CM partagé par plusieurs groupes touchés
    # par des perturbations différentes).
    # ------------------------------------------------------------------
    X               = {}
    valid_placements = defaultdict(list)  # item_key -> [(d, start_min, r_name), ...]
    item_keys       = []                  # item_key[i] correspond à to_reschedule[i]

    nb_blocked_teacher = {}
    nb_blocked_group = {}
    nb_blocked_room = {}

    for idx, item in enumerate(to_reschedule):
        item_key = (item.course, idx)
        item_keys.append(item_key)

        c_key = base_course_id(item.course)
        c     = course_map.get(c_key) or course_map.get(str(c_key))
        if c is None:
            continue
        dur = hm(item.heure_fin) - hm(item.heure_debut)
        locked_slot = (locked_slots or {}).get(id(item))

        nb_blocked_teacher[id(item)] = 0
        nb_blocked_group[id(item)] = 0
        nb_blocked_room[id(item)] = 0

        for d in range(min_day, nb_days):
            if locked_slot is not None and d != locked_slot[0]:
                continue
            for start_min in valid_starts:
                if locked_slot is not None and min_to_hm(start_min) != locked_slot[1]:
                    continue
                end_min = start_min + dur

                # Absent intervals
                blocked = False
                for (ad, ah_debut, ah_fin) in absent_intervals:
                    if ad == d and start_min < hm(ah_fin) and hm(ah_debut) < end_min:
                        blocked = True
                        break
                if blocked:
                    continue

                # Lunch constraint — basée sur occupation fixe uniquement
                lunch_ov = max(0, min(end_min, lunch_fin_min) - max(start_min, lunch_debut_min))
                if lunch_ov > 0:
                    lw    = lunch_fin_min - lunch_debut_min
                    g_occ = max((lunch_fixed_group.get((g.id, d), 0) for g in item.group), default=0)
                    t_occ = lunch_fixed_teacher.get((item.teacher.id, d), 0)
                    if (lw - g_occ - lunch_ov) < LUNCH_MIN_FREE_MINUTES:
                        continue
                    if (lw - t_occ - lunch_ov) < LUNCH_MIN_FREE_MINUTES:
                        continue

                for r in rooms:
                    # Type et capacité
                    if r.capacity < sum(g.headcount for g in item.group):
                        continue
                    # session_type (CSV) donne le type de CETTE séance ; c.room_types liste TOUS les types du cours.
                    # Si session_type est générique (ex: "TP") et c.room_types contient un sous-type plus précis
                    # (ex: "TP_SI"), on utilise le sous-type. Sinon on garde session_type tel quel.
                    if item.session_type:
                        specific = [rt for rt in c.room_types if rt.startswith(item.session_type) and rt != item.session_type]
                        req = specific if specific else [item.session_type]
                    else:
                        req = c.room_types
                    if req and not any(rt in r.room_types for rt in req):
                        continue

                    # Conflit avec cours fixes — groupe via bisect O(log n)
                    if any(_group_conflict(gid, d, start_min, end_min, group_day_index)
                           for gid in _expand_groups(item.group)):
                        continue
                    conflict = any(
                        (r.name,          d, m) in occ_room or
                        (item.teacher.id, d, m) in occ_teacher
                        for m in range(start_min, end_min)
                    )
                    if conflict:
                        continue

                    # --- checks créneaux bloqués par entité ---
                    # teacher_ok = not any(
                    #     d == ad and start_min < hm(ah_fin) and hm(ah_debut) < end_min
                    #     for (ad, ah_debut, ah_fin) in teacher_blocked.get(item.teacher.id, [])
                    # )
                    # if not teacher_ok:
                    #     continue

                    # group_ok = not any(
                    #     any(d == ad and start_min < hm(ah_fin) and hm(ah_debut) < end_min
                    #         for (ad, ah_debut, ah_fin) in groups_blocked.get(g.id, []))
                    #     for g in item.group
                    # )
                    # if not group_ok:
                    #     continue

                    # room_ok = not any(
                    #     d == ad and start_min < hm(ah_fin) and hm(ah_debut) < end_min
                    #     for (ad, ah_debut, ah_fin) in rooms_blocked.get(r.name, [])
                    # )
                    # if not room_ok:
                    #     continue

                    blocked = False
                    for (abd, abh, abf) in teacher_blocked.get(item.teacher.id, []):
                        if abd == d and start_min < hm(abf) and hm(abh) < end_min:
                            blocked = True; nb_blocked_teacher[id(item)] += 1; break
                    if not blocked:
                        for g in item.group:
                            for (abd, abh, abf) in groups_blocked.get(g.id, []):
                                if abd == d and start_min < hm(abf) and hm(abh) < end_min:
                                    blocked = True; nb_blocked_group[id(item)] += 1; break
                            if blocked: break
                    if not blocked:
                        for (abd, abh, abf) in rooms_blocked.get(r.name, []):
                            if abd == d and start_min < hm(abf) and hm(abh) < end_min:
                                blocked = True; nb_blocked_room[id(item)] += 1; break
                    if blocked:
                        continue

                    key = (item_key, d, start_min, r.name)
                    X[key] = model.NewBoolVar(f"x_{item.course}_{idx}_{d}_{start_min}_{r.name}")
                    valid_placements[item_key].append((d, start_min, r.name))


    # ------------------------------------------------------------------
    # Contrainte 1 — chaque cours placé exactement une fois
    # (les cours sans placement valide sont directement annulés)
    # ------------------------------------------------------------------
    placed_items:    List[ScheduleItem] = []
    placed_keys:     list               = []
    cancelled_items: List[ScheduleItem] = []

    for item, item_key in zip(to_reschedule, item_keys):
        placements = valid_placements[item_key]
        if not placements:
            c_key = base_course_id(item.course)
            c     = course_map.get(c_key) or course_map.get(str(c_key))
            cname = c.name if c else str(item.course)
            types = c.room_types if c else "?"
            reason = []
            if nb_blocked_teacher.get(id(item), 0) > 0 : reason.append(f"Aucun créneau avec un professeur disponible")
            if nb_blocked_group.get(id(item), 0) > 0 : reason.append(f"Aucun créneau où le groupe est disponible")
            if nb_blocked_room.get(id(item), 0) > 0 : reason.append(f"Aucun créneau avec une salle disponible")
            print(f"  [!] Aucun placement valide pour {cname} {', '.join([g.id for g in item.group])} ({fmt_abs_day(item.day)}, {item.heure_debut}-{item.heure_fin}) — {', '.join(reason) if reason else 'contraintes planning'}")

            cancelled_items.append(item)
            continue
        placed_items.append(item)
        placed_keys.append(item_key)
        model.AddExactlyOne(X[(item_key, d, s, r)] for (d, s, r) in placements)

    # Si aucun cours n'a de placement valide, inutile de lancer CP-SAT
    if not placed_items:
        return fixed_schedule, cancelled_items, "CANCELLED"

    # ------------------------------------------------------------------
    # Contrainte 2 — pas de chevauchement via IntervalVar + AddNoOverlap
    # ------------------------------------------------------------------
    group_ivs   = defaultdict(list)   # (group, day)      -> [IntervalVar]
    teacher_ivs = defaultdict(list)   # (teacher_id, day) -> [IntervalVar]
    room_ivs    = defaultdict(list)   # (room_name, day)  -> [IntervalVar]

    # Les conflits fixes ↔ perturbés sont gérés par le pré-filtrage (valid_placements).
    # On n'ajoute PAS d'intervalles fixes dans le modèle : si le planning original
    # a des chevauchements légitimes (ex. amphi : même prof, deux groupes, même heure),
    # des intervalles fixes provoqueraient un INFEASIBLE immédiat dans AddNoOverlap.
    # Les AddNoOverlap ci-dessous gèrent uniquement les conflits perturbé ↔ perturbé.

    # Intervalles OPTIONNELS (cours perturbés — actifs ssi X=1)
    for item, item_key in zip(placed_items, placed_keys):
        dur = hm(item.heure_fin) - hm(item.heure_debut)

        for (d, start_min, r_name) in valid_placements[item_key]:
            end_min = start_min + dur
            bv = X[(item_key, d, start_min, r_name)]
            sfx = f"{item.course}_{item_key[1]}_{d}_{start_min}"

            for gid in _expand_groups(item.group):
                group_ivs[(gid, d)].append(
                    model.NewOptionalIntervalVar(start_min, dur, end_min, bv, f"iv_g_{sfx}_{gid}"))
            teacher_ivs[(item.teacher.id, d)].append(
                model.NewOptionalIntervalVar(start_min, dur, end_min, bv, f"iv_t_{sfx}"))
            room_ivs[(r_name, d)].append(
                model.NewOptionalIntervalVar(start_min, dur, end_min, bv, f"iv_r_{sfx}_{r_name}"))

    # AddNoOverlap par entité-jour (gère fixes ↔ perturbés et perturbés ↔ perturbés)
    for ivs in group_ivs.values():
        if len(ivs) > 1:
            model.AddNoOverlap(ivs)
    for ivs in teacher_ivs.values():
        if len(ivs) > 1:
            model.AddNoOverlap(ivs)
    for ivs in room_ivs.values():
        if len(ivs) > 1:
            model.AddNoOverlap(ivs)

    # ------------------------------------------------------------------
    # Objectif soft — minimize ∑ penalty × X
    # (pénalités calculées sur l'occupation fixe uniquement)
    # ------------------------------------------------------------------
    scorers   = soft_scorers or []
    penalties = []
    room_map  = {r.name: r for r in rooms}   # aussi utilisé à la reconstruction

    if scorers:
        for item, item_key in zip(placed_items, placed_keys):
            c_key = base_course_id(item.course)
            c     = course_map.get(c_key) or course_map.get(str(c_key))
            dur   = hm(item.heure_fin) - hm(item.heure_debut)
            for (d, start_min, r_name) in valid_placements[item_key]:
                r = room_map.get(r_name)
                if r is None:
                    continue
                hd = min_to_hm(start_min)
                hf = min_to_hm(start_min + dur)
                soft_pen = sum(
                    w * fn(item, c, d, hd, hf, r,
                           group_day_index, occ_teacher, lunch_debut_min, lunch_fin_min)
                    for fn, w in scorers
                )
                if soft_pen != 0:
                    pen_int = int(round(soft_pen * 100))
                    penalties.append(pen_int * X[(item_key, d, start_min, r_name)])

    if penalties:
        model.Minimize(sum(penalties))

    # ------------------------------------------------------------------
    # Résolution
    # ------------------------------------------------------------------
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = timeout
    solver.parameters.num_search_workers  = num_workers

    cb     = BestSolutionCallback()
    status = solver.Solve(model, cb)
    status_name = solver.StatusName(status)

    if status_name not in ("OPTIMAL", "FEASIBLE"):
        return None, to_reschedule, status_name

    # ------------------------------------------------------------------
    # Reconstruction du planning résolu
    # ------------------------------------------------------------------
    new_schedule = list(fixed_schedule)

    for item, item_key in zip(placed_items, placed_keys):
        dur = hm(item.heure_fin) - hm(item.heure_debut)
        placed = False
        for (d, start_min, r_name) in valid_placements[item_key]:
            if solver.Value(X[(item_key, d, start_min, r_name)]) == 1:
                r_obj    = room_map.get(r_name)
                new_item = item._replace(
                    day=d,
                    heure_debut=min_to_hm(start_min),
                    heure_fin=min_to_hm(start_min + dur),
                    room=r_name,
                    building=r_obj.bat if r_obj else item.building,
                )
                new_schedule.append(new_item)
                placed = True
                break
        if not placed:
            cancelled_items.append(item)

    return new_schedule, cancelled_items, status_name


#?############################################################################
#? Solve pour toutes les perturbations de type 1,2,3 (CP-SAT+Greedy fallback)
#?############################################################################
def resolve_all(
    to_reschedule:    List[ScheduleItem],
    fixed_schedule:   List[ScheduleItem],
    courses:          List[Course],
    rooms:            List[Room],
    nb_days:          int,
    valid_starts:     List[int],
    absent_intervals: AbsentIntervals,
    teacher_blocked:  dict,  # teacher_id -> [(day, h_debut, h_fin), ...]
    groups_blocked:    dict,  # group_id   -> [(day, h_debut, h_fin), ...]
    rooms_blocked:     dict,  # room_name  -> [(day, h_debut, h_fin), ...]
    lunch_debut_min:  int,
    lunch_fin_min:    int,
    soft_scorers:     Optional[ScorerList] = None,
    solver_timeout:   int = 60,
    min_day:          int = 0,
    locked_slots:     Optional[dict] = None,
) -> Tuple[List[ScheduleItem], List[ScheduleItem], str, List[ScheduleItem]]:
    """
    Tente CP-SAT en premier.  Si le solveur échoue, repasse sur le greedy.
    Retourne (new_schedule, cancelled, status, rescheduled).
    rescheduled = items effectivement replacés avec leur nouvelle position.
    locked_slots = {id(item): (day, heure_debut)} pour forcer jour ET créneau (type 2).
    """
    if not to_reschedule:
        return list(fixed_schedule), [], "OPTIMAL", []

    n_fixed = len(fixed_schedule)

    to_reschedule_fr = [it for it in to_reschedule if it.day >= basics.MIN_DAY]
    fixed_schedule   = list(fixed_schedule) + [it for it in to_reschedule if it.day < basics.MIN_DAY]

    try:
        new_sched, cancelled, status = solve_all_perturbations(
            to_reschedule=to_reschedule_fr,
            fixed_schedule=fixed_schedule,
            courses=courses,
            rooms=rooms,
            nb_days=nb_days,
            valid_starts=valid_starts,
            absent_intervals=absent_intervals,
            teacher_blocked=teacher_blocked,
            groups_blocked=groups_blocked,
            rooms_blocked=rooms_blocked,
            lunch_debut_min=lunch_debut_min,
            lunch_fin_min=lunch_fin_min,
            soft_scorers=soft_scorers,
            timeout=solver_timeout,
            min_day=min_day,
            locked_slots=locked_slots,
        )
    except Exception as e:
        print(f"  → CP-SAT : EXCEPTION ({type(e).__name__}: {e}) — fallback greedy.")
        status = f"EXCEPTION:{type(e).__name__}"
        new_sched, cancelled = None, to_reschedule

    if status in ("OPTIMAL", "FEASIBLE"):
        print(f"  → CP-SAT : {status} — {len(cancelled)} cours non placé(s).")
        return new_sched, cancelled, status, new_sched[n_fixed:]

    print(f"  → CP-SAT : {status} — fallback greedy.")
    new_sched, cancelled, rescheduled = greedy_fallback_with_blocked(
        to_reschedule=to_reschedule,
        fixed_schedule=fixed_schedule,
        courses=courses,
        rooms=rooms,
        nb_days=nb_days,
        valid_starts=valid_starts,
        absent_intervals=absent_intervals,
        teacher_blocked=teacher_blocked,
        groups_blocked=groups_blocked,
        rooms_blocked=rooms_blocked,
        lunch_debut_min=lunch_debut_min,
        lunch_fin_min=lunch_fin_min,
        soft_scorers=soft_scorers,
        min_day=min_day,
        locked_slots=locked_slots,
    )
    return new_sched, cancelled, "GREEDY", rescheduled


#!##############################################################
#! Solve toutes les perturbations en même temps
#!##############################################################
def full_solve(schedule: List[ScheduleItem],
               list_perturb: List[dict],
               courses: List[Course],
               rooms: List[Room],
               teachers: List[Teacher],
               groups: List[Group],
               valid_starts: List[int],
               lunch_debut_min: int,
               lunch_fin_min: int,
               soft_scorers: Optional[ScorerList] = None,
               solver_timeout: int = 60,
               teacher_replacement_fn=None,
               move_fn=None,
               move_all_fn=None,
               permutation_fn=None,
               room_change_fn=None,
               add_session_fn=None,
               remove_session_fn=None,
               min_day: int = 0,
               nb_days: int = 0):
    """
    Résout toutes les perturbations en plusieurs phases :

    Phase 0 — Suppression de session (type 9):
        Toutes les sessions impactées par cette perturbation sont supprimées,
        laissant derrière elles plus de place pour gérer les autres perturbations

    Phase 1 — Placement global (types 1/2/3) :
        Tous les cours affectés par des absences prof/salle/créneau sont collectés
        et replacés en une seule passe CP-SAT + greedy fallback.

    Phase 2 — Affectation prof (type 4) :
        Chaque perturbation de remplacement est traitée séquentiellement APRÈS le
        placement, sur le schedule issu de la phase 1.

    Phase 3 — Déplacement (type 5) :
        Chaque déplacement est appliqué séquentiellement APRÈS la phase 2, avec
        le picker automatique (best_slot_fn) pour ne pas bloquer la résolution.

    Phase 4 — Permutation (type 6) :
            Chaque permutation est appliquée séquentiellement APRÈS la phase 3.
    
    Phase 5 — Changement de salle (type 7) :
            Chaque chnagement de salle est appliqué séquentiellement APRÈS la phase 5.
    
    Phase 6 — Ajout de session (type 8) :
            Chaque ajout est appliqué séquentiellement APRÈS la phase 5.

    teacher_replacement_fn / move_fn / best_slot_fn / add_session_fn : callables de scenarios.py,
        passés en paramètre pour éviter l'import circulaire solver ↔ scenarios.

    Retourne (new_schedule, all_cancelled, n_attempted, solver_status, rescheduled).
    """

    ################* Variables globales dérivées du planning initial
    all_days    = sorted(set(item.day for item in schedule))
    # nb_days fourni par l'appelant (ex: 75 pour un semestre 15 semaines).
    # Sinon on déduit depuis le planning — peut manquer des jours vides en fin de semestre.
    if nb_days <= 0:
        nb_days = (max(all_days) + 1) if all_days else 0
    all_groups  = {g.id for item in schedule for g in item.group}
    all_teachers = {item.teacher.id for item in schedule}
    all_rooms   = {item.room for item in schedule if item.room != "?"}
    all_courses = {item.course for item in schedule}

    global_absent = collect_absent_intervals(list_perturb, groups, rooms, nb_days)

    ################* Séparation des perturbations par nature
    # Types 1/2/3 = placement (où/quand mettre le cours)
    # Type 4      = affectation (qui enseigne le cours, créneau inchangé)
    # Type 5      = déplacement manuel (après stabilisation du planning)
    placement_perturbs   = [p for p in list_perturb if p["type"] in (1, 2, 3)]
    replacement_perturbs = [p for p in list_perturb if p["type"] == 4]
    move_perturbs        = [p for p in list_perturb if p["type"] == 5]
    perm_perturbs        = [p for p in list_perturb if p["type"] == 6]
    room_change_perturbs = [p for p in list_perturb if p["type"] == 7]
    add_session_perturbs = [p for p in list_perturb if p["type"] == 8]
    remove_session_perturbs = [p for p in list_perturb if p["type"] == 9]

    new_schedule  = list(schedule)
    p0_done       = []
    p0_not_done   = []

    ################! PHASE 0 : Suppression des sessions demandées
    print(f"\n--- Phase 0 : suppression de sessions ({len(remove_session_perturbs)} perturbation(s) type 9) ---")
    n_attempted_remove = 0
    if remove_session_perturbs:
        if remove_session_fn is None:
            print("  [!] Perturbations type 9 ignorées : remove_session_fn non fourni.")
        else:
            # Fusionner tous les to_remove en une seule liste
            to_remove_all = []
            for perturb in remove_session_perturbs:
                to_remove_all.extend(perturb["to_remove"])

            n_attempted_remove += len(to_remove_all)
            print(f"  {len(to_remove_all)} sessions à supprimer ...")

            new_schedule, p0_done, p0_not_done, remove_status = remove_session_fn(
                schedule  = new_schedule,
                to_remove = to_remove_all,
            )

            for item in p0_done:
                print(f"    ✓ '{item.course}' ({item.session_type})[{', '.join(g.id for g in item.group)}] {fmt_abs_day(item.day)} {item.heure_debut}–{item.heure_fin} supprimée avec succès")

            for item in p0_not_done:
                print(f"    ✗ '{item.course}' ({item.session_type}) [{', '.join(g.id for g in item.group)}] {fmt_abs_day(item.day)} {item.heure_debut}–{item.heure_fin} n'a pas pu être supprimée (non trouvée dans l'edt)")

            p0_ok     = len(p0_done)
            p0_failed = len(p0_not_done)
            summary_parts = []
            if p0_ok:
                summary_parts.append(f"{p0_ok} suppression(s)")
            if p0_failed:
                summary_parts.append(f"{p0_failed} sessions non supprimées")
            print(f"  ↳ Phase 0 : " + (", ".join(summary_parts) if summary_parts else "aucun changement"))
    
    ################! PHASE 1 : collecte des infos et résolution placement
    info_perturb = {
        "affected":        [],
        "teacher_blocked": {},
        "rooms_blocked":   {},
        "groups_blocked":  {},
    }
    _affected_ids  = set()   # pour dédupliquer les cours touchés par plusieurs perturbations
    _type13_ids    = set()   # items touchés par type 1 ou 3 → ne pas verrouiller leur créneau

    print(f"\n--- Phase 1 : placement de ({len(placement_perturbs)} perturbation(s) type 1/2/3) ---")
    for perturb in placement_perturbs:
        if perturb["type"] == 1:
            res = analyze_teacher_absent(new_schedule, perturb["teacher_id"], perturb["intervals"])
            for item in res["affected"]:
                _type13_ids.add(id(item))
                if id(item) not in _affected_ids:
                    _affected_ids.add(id(item))
                    info_perturb["affected"].append(item)
            for tid, intervals in res["teacher_blocked"].items():
                if tid in info_perturb["teacher_blocked"]:
                    info_perturb["teacher_blocked"][tid] += intervals
                else:
                    info_perturb["teacher_blocked"][tid] = list(intervals)

        elif perturb["type"] == 2:
            res = analyze_room_unavailable(new_schedule, perturb["room"], perturb["intervals"], all_days)
            for item in res["affected"]:
                if id(item) not in _affected_ids:
                    _affected_ids.add(id(item))
                    info_perturb["affected"].append(item)
            for rid, intervals in res["rooms_blocked"].items():
                if rid in info_perturb["rooms_blocked"]:
                    info_perturb["rooms_blocked"][rid] += intervals
                else:
                    info_perturb["rooms_blocked"][rid] = list(intervals)

        elif perturb["type"] == 3:
            res = analyze_free_slot(new_schedule, perturb["intervals"], all_groups, perturb["groups"])
            for item in res["affected"]:
                _type13_ids.add(id(item))
                if id(item) not in _affected_ids:
                    _affected_ids.add(id(item))
                    info_perturb["affected"].append(item)
            for gid, intervals in res["groups_blocked"].items():
                if gid in info_perturb["groups_blocked"]:
                    info_perturb["groups_blocked"][gid] += intervals
                else:
                    info_perturb["groups_blocked"][gid] = list(intervals)

    # fixed_schedule = tout sauf les cours à replacer (les créneaux libérés ne bloquent pas)
    affected_set   = _affected_ids
    fixed_schedule = [item for item in new_schedule if id(item) not in affected_set]

    # locked_slots pour les items de type 2 : même jour ET même créneau, salle seule change.
    # EXCEPTION : si le même item est aussi touché par un type 1 ou 3, le créneau doit changer
    # → on ne le verrouille pas (_type13_ids prime sur _type2_affected).
    _type2_affected = set()
    for perturb in placement_perturbs:
        if perturb["type"] == 2:
            res = analyze_room_unavailable(new_schedule, perturb["room"], perturb["intervals"], all_days)
            _type2_affected.update(id(it) for it in res["affected"])
    locked_slots = {
        id(item): (item.day, item.heure_debut)
        for item in info_perturb["affected"]
        if id(item) in _type2_affected and id(item) not in _type13_ids
    } or None

    new_schedule, placement_cancelled, solver_status, placement_rescheduled = resolve_all(
        to_reschedule    = info_perturb["affected"],
        fixed_schedule   = fixed_schedule,
        courses          = courses,
        rooms            = rooms,
        nb_days          = nb_days,
        valid_starts     = valid_starts,
        absent_intervals = [],          # tout est dans teacher/rooms/groups_blocked
        teacher_blocked  = info_perturb["teacher_blocked"],
        groups_blocked   = info_perturb["groups_blocked"],
        rooms_blocked    = info_perturb["rooms_blocked"],
        lunch_debut_min  = lunch_debut_min,
        lunch_fin_min    = lunch_fin_min,
        soft_scorers     = soft_scorers,
        solver_timeout   = solver_timeout,
        min_day          = min_day,
        locked_slots     = locked_slots,
    )
    n_attempted        = len(info_perturb["affected"])
    all_truly_cancelled = list(placement_cancelled)   # cours absents de l'EDT (type 1/2/3)
    all_put_back        = []                           # cours remis en place (types 5/6/7)
    all_rescheduled     = list(placement_rescheduled)
    p1_ok = n_attempted - len(placement_cancelled)
    print(f"  ↳ Phase 1 : {p1_ok}/{n_attempted} cours replacés — statut CP-SAT : {solver_status}"
          + (f" ({len(placement_cancelled)} annulés)" if placement_cancelled else ""))

    ################! PHASE 2 : affectation prof (type 4), séquentielle sur le résultat de la phase 1
    # Chaque perturbation de remplacement travaille sur le schedule stabilisé de la phase précédente.
    # Les créneaux et salles sont fixés — on cherche uniquement qui enseigne.
    print(f"\n--- Phase 2 : affectation prof de ({len(replacement_perturbs)} perturbation(s) type 4) ---")
    p2_statuses = []
    if replacement_perturbs:
        if teacher_replacement_fn is None:
            print("  [!] Perturbations type 4 ignorées : teacher_replacement_fn non fourni.")
        else:
            for i, perturb in enumerate(replacement_perturbs, 1):
                tid_label = perturb.get("teacher_id") or perturb.get("course_name") or f"perturb#{i}"
                print(f"  [{i}/{len(replacement_perturbs)}] Remplacement pour {tid_label}...")
                # new_schedule est le planning stabilisé après placement — les créneaux
                # des cours à couvrir sont donc déjà à leur position finale.
                new_schedule, p4_cancelled, p4_n, p4_status, p4_log = teacher_replacement_fn(
                    new_schedule, courses, rooms, teachers, nb_days,
                    lunch_debut_min  = lunch_debut_min,
                    lunch_fin_min    = lunch_fin_min,
                    global_absent    = global_absent,
                    absent_teacher_id   = perturb.get("teacher_id"),
                    target_course_ids   = perturb.get("course_ids"),
                    target_groups       = perturb.get("target_groups"),
                    target_session_type = perturb.get("target_session_type"),
                    absent_intervals    = perturb.get("intervals"),
                )
                n_attempted   += p4_n
                all_truly_cancelled += p4_cancelled
                p2_statuses.append(p4_status)
                print(f"     → {p4_status} — {p4_n - len(p4_cancelled)}/{p4_n} cours assignés.")

    ################! PHASE 3 : déplacements manuels (type 5), en une passe via move_all
    print(f"\n--- Phase 3 : déplacements ({len(move_perturbs)} perturbation(s) type 5) ---")
    if move_perturbs:
        if move_all_fn is None:
            print("  [!] Perturbations type 5 ignorées : move_all_fn non fourni.")
        else:
            course_map_p3     = {c.id: c for c in courses}
            to_move_input     = [(p["to_move"], p["target_day"], p.get("heure_debut")) for p in move_perturbs]
            valid_starts_move = sorted(set(hm(it.heure_debut) for it in new_schedule))
            sched_snapshot    = list(new_schedule)

            new_schedule, _all_done, nb_done, placed_list = move_all_fn(
                schedule        = new_schedule,
                to_move         = to_move_input,
                nb_days         = nb_days,
                lunch_debut_min = lunch_debut_min,
                lunch_fin_min   = lunch_fin_min,
                valid_starts    = valid_starts_move,
                courses         = courses,
                rooms           = rooms,
                soft_scorers    = soft_scorers,
                slot_picker_fn  = _best_slot,
                solver_timeout  = solver_timeout,
                global_absent   = global_absent,
            )
            n_attempted += len(move_perturbs)

            placed_idx = 0
            for i, (perturb, (item, target_d, req_hd)) in enumerate(zip(move_perturbs, to_move_input), 1):
                c_key      = base_course_id(item.course)
                c_obj      = course_map_p3.get(c_key)
                cname      = c_obj.name if c_obj else str(item.course)
                groups_str = ", ".join(g.id for g in item.group)
                print(f"  [{i}/{len(move_perturbs)}] '{cname}' [{groups_str}] {fmt_abs_day(item.day)} {item.heure_debut}–{item.heure_fin} salle {item.room}", end="  →  ", flush=True)
                if item in sched_snapshot:
                    placed = placed_list[placed_idx] if placed_idx < len(placed_list) else None
                    placed_idx += 1
                    if placed is not None:
                        all_rescheduled.append(placed)
                        perturb["placed_item"] = placed
                        as_requested = (req_hd is None or placed.heure_debut == req_hd)
                        perturb["placed_as_requested"] = as_requested
                        print(f"{fmt_abs_day(placed.day)} {placed.heure_debut}–{placed.heure_fin} salle {placed.room}")
                        if not as_requested:
                            print(f"  ⚠  Créneau demandé : {req_hd} — créneau attribué : {placed.heure_debut} (créneau demandé indisponible)")
                    else:
                        perturb["placed_item"] = None
                        perturb["placed_as_requested"] = False
                        new_schedule.append(item)  # remise à la place originale
                        all_put_back.append(item)
                        print("ÉCHEC — cours remis à sa place originale")
                else:
                    perturb["placed_item"] = None
                    perturb["placed_as_requested"] = False
                    print("IGNORÉ (cours déplacé par une perturbation antérieure)")

            # Récap phase 3
            p3_ok      = sum(1 for p in move_perturbs if p.get("placed_item") is not None)
            p3_ignored = sum(1 for p in move_perturbs if p.get("placed_item") is None and p.get("placed_as_requested") is None)
            p3_failed  = len(move_perturbs) - p3_ok - p3_ignored
            print(f"  ↳ Phase 3 : {p3_ok}/{len(move_perturbs)} déplacés"
                  + (f", {p3_failed} remis en place" if p3_failed else "")
                  + (f", {p3_ignored} ignorés" if p3_ignored else ""))

    ################! PHASE 4 : permutations (type 6), séquentielles après phase 3
    print(f"\n--- Phase 4 : permutations ({len(perm_perturbs)} perturbation(s) type 6) ---")
    p4_ok = 0
    if perm_perturbs:
        if permutation_fn is None:
            print("  [!] Perturbations type 6 ignorées : permutation_fn non fourni.")
        else:
            course_map_p4 = {c.id: c for c in courses}
            for i, perturb in enumerate(perm_perturbs, 1):
                perm1, perm2 = perturb["perm1"], perturb["perm2"]
                c1_obj = course_map_p4.get(base_course_id(perm1.course))
                c2_obj = course_map_p4.get(base_course_id(perm2.course))
                c1_name = c1_obj.name if c1_obj else str(perm1.course)
                c2_name = c2_obj.name if c2_obj else str(perm2.course)
                print(f"  [{i}/{len(perm_perturbs)}] '{c1_name}' [{', '.join(g.id for g in perm1.group)}] {fmt_abs_day(perm1.day)} {perm1.heure_debut}–{perm1.heure_fin}"
                      f"  ⇄  '{c2_name}' [{', '.join(g.id for g in perm2.group)}] {fmt_abs_day(perm2.day)} {perm2.heure_debut}–{perm2.heure_fin}", flush=True)
                valid_starts_perm = sorted(set(hm(item.heure_debut) for item in new_schedule))
                new_schedule, done, placed_items = permutation_fn(
                    schedule=new_schedule,
                    perm1=perm1, perm2=perm2,
                    lunch_debut_min=lunch_debut_min,
                    lunch_fin_min=lunch_fin_min,
                    valid_starts=valid_starts_perm,
                    courses=courses,
                    rooms=rooms,
                    soft_scorers=soft_scorers,
                    slot_picker_fn=_best_slot,
                    keep_room=perturb.get("keep_room", False),
                    move_courses=perturb.get("move_courses", True),
                    global_absent=global_absent,
                )
                n_attempted += 2
                perturb["placed_items"] = placed_items
                if done and placed_items:
                    p4_ok += 1
                    all_rescheduled.extend([perm1, perm2])
                    for pi in placed_items:
                        if pi is not None:
                            print(f"    → {fmt_abs_day(pi.day)} {pi.heure_debut}–{pi.heure_fin} salle {pi.room}")
                elif done is None:
                    # print("  IGNORÉ (cours dans le passé)")
                    pass
                else:
                    all_put_back.extend([perm1, perm2])
                    print("  ÉCHEC — cours remis à leurs places originales")
            print(f"  ↳ Phase 4 : {p4_ok}/{len(perm_perturbs)} permutations réussies")

    ################! PHASE 5 : changements de salle (type 7), une seule passe CP-SAT globale
    print(f"\n--- Phase 5 : changements de salle ({len(room_change_perturbs)} perturbation(s) type 7) ---")
    p5_ok = 0
    p5_failed = 0
    if room_change_perturbs:
        if room_change_fn is None:
            print("  [!] Perturbations type 7 ignorées : room_change_fn non fourni.")
        else:
            course_map_p5 = {c.id: c for c in courses}

            # Fusionner tous les to_change en une seule liste pour CP-SAT global
            # best_room est encodé par tuple — aucune info perdue
            to_change_all = []
            for perturb in room_change_perturbs:
                to_change_all.extend(perturb["to_change"])

            n_attempted += len(to_change_all)
            print(f"  {len(to_change_all)} cours à changer de salle (passe CP-SAT unique)...")

            # Index salle d'origine pour détecter "victoire invisible"
            orig_room = {}
            for tup in to_change_all:
                item = tup[0]
                key = (base_course_id(item.course), item.day, item.heure_debut,
                       tuple(sorted(g.id for g in item.group)))
                orig_room[key] = item.room

            new_schedule, exact_items, moved_items, rc_status, not_done, specific_not_done = room_change_fn(
                schedule        = new_schedule,
                to_change       = to_change_all,
                lunch_debut_min = lunch_debut_min,
                lunch_fin_min   = lunch_fin_min,
                courses         = courses,
                rooms           = rooms,
                soft_scorers    = soft_scorers,
                solver_timeout  = solver_timeout,
                global_absent   = global_absent,
            )

            for item in exact_items:
                c_obj = course_map_p5.get(base_course_id(item.course))
                cname = c_obj.name if c_obj else str(item.course)
                print(f"    ✓ '{cname}' [{', '.join(g.id for g in item.group)}] {fmt_abs_day(item.day)} {item.heure_debut}–{item.heure_fin} → salle {item.room} (salle demandée)")

            for item in moved_items:
                c_obj = course_map_p5.get(base_course_id(item.course))
                cname = c_obj.name if c_obj else str(item.course)
                key = (base_course_id(item.course), item.day, item.heure_debut,
                       tuple(sorted(g.id for g in item.group)))
                old_room = orig_room.get(key, "?")
                if item.room == old_room:
                    print(f"    ~ '{cname}' [{', '.join(g.id for g in item.group)}] {fmt_abs_day(item.day)} {item.heure_debut}–{item.heure_fin} → salle {item.room} (salle d'origine — optimale selon les scorers)")
                else:
                    print(f"    ~ '{cname}' [{', '.join(g.id for g in item.group)}] {fmt_abs_day(item.day)} {item.heure_debut}–{item.heure_fin} {old_room} → salle {item.room} (meilleure alternative)")

            for item in not_done:
                c_obj = course_map_p5.get(base_course_id(item.course))
                cname = c_obj.name if c_obj else str(item.course)
                print(f"    ✗ '{cname}' [{', '.join(g.id for g in item.group)}] {fmt_abs_day(item.day)} {item.heure_debut}–{item.heure_fin} — aucune salle valide trouvée, remis en place")
                new_schedule.append(item)
                all_put_back.append(item)

            for item in specific_not_done:
                c_obj = course_map_p5.get(base_course_id(item.course))
                cname = c_obj.name if c_obj else str(item.course)
                print(f"    ✗ '{cname}' [{', '.join(g.id for g in item.group)}] {fmt_abs_day(item.day)} {item.heure_debut}–{item.heure_fin} — salle spécifique refusée, alternative non demandée, remis en place")
                new_schedule.append(item)
                all_put_back.append(item)

            p5_exact  = len(exact_items)
            p5_fallback = len(moved_items)
            p5_failed = len(not_done) + len(specific_not_done)
            p5_ok = p5_exact + p5_fallback
            summary_parts = []
            if p5_exact:
                summary_parts.append(f"{p5_exact} salle(s) exacte(s)")
            if p5_fallback:
                summary_parts.append(f"{p5_fallback} alternative(s)")
            if p5_failed:
                summary_parts.append(f"{p5_failed} remis en place")
            print(f"  ↳ Phase 5 : " + (", ".join(summary_parts) if summary_parts else "aucun changement"))

    ################! PHASE 6 : ajout de sessions (type 8), une seule passe CP-SAT globale
    print(f"\n--- Phase 6 : ajout de sessions ({len(add_session_perturbs)} perturbation(s) type 8) ---")
    n_attempted_add = 0
    p6_ok = 0
    p6_failed = 0
    p6_done = []
    p6_not_done = []
    if add_session_perturbs:
        if add_session_fn is None:
            print("  [!] Perturbations type 8 ignorées : add_session_fn non fourni.")
        else:
            course_map_p6 = {c.id: c for c in courses}

            # Fusionner tous les to_add en une seule liste pour CP-SAT global
            to_add_all = []
            for perturb in add_session_perturbs:
                to_add_all.extend(perturb["to_add"])
    
            n_attempted_add += len(to_add_all)
            print(f"  {len(to_add_all)} sessions à ajouter (passe CP-SAT unique)...")
    
    
            new_schedule, done, not_done, add_status   = add_session_fn(
                    schedule        = new_schedule,
                    to_add          = to_add_all,
                    lunch_debut_min = lunch_debut_min,
                    lunch_fin_min   = lunch_fin_min,
                    nb_days         = nb_days,
                    courses         = courses,
                    rooms           = rooms,
                    soft_scorers    = soft_scorers,
                    solver_timeout  = solver_timeout,
                    global_absent   = global_absent,
                )
    
            for item in done:
                c_obj = course_map_p6.get(base_course_id(item.course))
                cname = c_obj.name if c_obj else str(item.course)
                print(f"    ✓ '{cname}' ({item.session_type})[{', '.join(g.id for g in item.group)}] {fmt_abs_day(item.day)} {item.heure_debut}–{item.heure_fin} ajoutée avec succès en salle {item.room}")
    
            for item in not_done:
                c_obj = course_map_p6.get(base_course_id(item.course))
                cname = c_obj.name if c_obj else str(item.course)
                day_str = fmt_abs_day(item.day) if item.day is not None else "Meilleur jour possible"
                print(f"    ✗ '{cname}' ({item.session_type}) [{', '.join(g.id for g in item.group)}] {day_str} {item.heure_debut}–{item.heure_fin} n'a pas pu être ajoutée")
                
    
    
            p6_done.extend(done)
            p6_not_done.extend(not_done)
            p6_ok  = len(done)
            p6_failed = len(not_done)
            summary_parts = []
            if p6_ok:
                summary_parts.append(f"{p6_ok} ajout(s)")
            if p6_failed:
                summary_parts.append(f"{p6_failed} sessions non ajoutées")
            print(f"  ↳ Phase 6 : " + (", ".join(summary_parts) if summary_parts else "aucun changement"))


    ################? RÉCAP GLOBAL
    total_failed = len(all_truly_cancelled) + len(all_put_back)
    total_ok = n_attempted - total_failed
    if 'rc_status' not in dir():
        rc_status = "N/A"
    if 'p3_ok' not in dir():
        p3_ok = 0
    if 'p6_ok' not in dir():
        p6_ok = 0
    if 'p0_ok' not in dir():
        p0_ok = 0
    total_added = p6_ok
    total_not_added = p6_failed

    # Statuts par phase
    phase_statuses = {
        "P0 Suppression de session (type 9)": (remove_status if remove_session_perturbs else "N/A"),
        "P1 Placement (type 1 à 3)": solver_status if placement_perturbs else "N/A",
        "P2 Remplacement (type 4)":       ", ".join(p2_statuses) if replacement_perturbs else "N/A",
        "P3 Déplacements (type 5)":       (f"{p3_ok}/{len(move_perturbs)} déplacé(s)" if move_perturbs else "N/A"),
        "P4 Permutations (type 6)":       (f"{p4_ok}/{len(perm_perturbs)} réussie(s)"  if perm_perturbs else "N/A"),
        "P5 Changement salle (type 7)":   (rc_status if room_change_perturbs else "N/A"),
        "P6 Ajout de sessions (type 8)":  (add_status if add_session_perturbs else "N/A"),
    }

    _w = max(len(k) for k in phase_statuses)
    print(f"\n{'='*60}")
    print(f"  RÉSUMÉ GLOBAL : {total_ok}/{n_attempted} cours traités avec succès")
    if n_attempted_remove:
        print(f"  Sessions supprimées (type 9) : {p0_ok}/{n_attempted_remove} supprimées avec succès")
    if n_attempted_add:
        print(f"  Sessions ajoutées (type 8) : {p6_ok}/{n_attempted_add} placées avec succès")
    if all_truly_cancelled:
        print(f"  Cours annulés (absents de l'EDT) : {len(all_truly_cancelled)}")
    if all_put_back:
        print(f"  Cours remis en place (demande non applicable) : {len(all_put_back)}")
    print(f"  {'Phase':{_w}}   Statut")
    print(f"  {'-'*_w}   {'-'*20}")
    for phase, status in phase_statuses.items():
        print(f"  {phase:{_w}} : {status}")
    print(f"{'='*60}")

    return new_schedule, all_truly_cancelled, all_put_back, n_attempted, phase_statuses, all_rescheduled, p6_done, p6_not_done, p0_done, p0_not_done, info_perturb["affected"]