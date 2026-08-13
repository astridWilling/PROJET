from basics import *
from greedy import build_occupations, try_place, greedy_fallback, is_valid_assignment_with_blocked, is_valid_assignment
from solver import solve_perturbation, resolve, find_candidates, solve_replacement, solve_move_all, solve_all_room_change, solve_all_add_sessions
from scorers import compute_hours, remaining_hours
import basics # pour pouvoir faire basics.MIN_DAY



# ===========================================================================
# HELPERS INTERNES
# ===========================================================================

def _valid_starts_from(schedule: List[ScheduleItem]) -> List[int]:
    """Heures de début réelles de l'EDT (en minutes), triées."""
    return sorted(set(hm(item.heure_debut) for item in schedule))

def _slot_blocked(day: int, start_min: int, end_min: int,
                  teacher_id: str, group_ids, room_name: str,
                  global_absent: dict) -> bool:
    """Vérifie si un slot (day, start_min, end_min) est bloqué par une absence globale."""
    for (d, hd, hf) in (global_absent or {}).get("teachers", {}).get(teacher_id, []):
        if day == d and start_min < hm(hf) and hm(hd) < end_min:
            return True
    for g in group_ids:
        for (d, hd, hf) in (global_absent or {}).get("groups", {}).get(g, []):
            if day == d and start_min < hm(hf) and hm(hd) < end_min:
                return True
    for (d, hd, hf) in (global_absent or {}).get("rooms", {}).get(room_name, []):
        if day == d and start_min < hm(hf) and hm(hd) < end_min:
            return True
    return False


def best_slot(candidates, day):
    """Picker automatique : retourne toujours le meilleur candidat (index 0)."""
    return 0 if candidates else None

def _room_reject_reason(item: "ScheduleItem", room_name: str,
                        course: "Course", room_map: dict) -> str:
    """Retourne la raison principale pour laquelle room_name ne peut pas accueillir item."""
    r = room_map.get(room_name)
    if r is None:
        return f"salle '{room_name}' introuvable"
    total_hc = sum(g.headcount for g in item.group)
    if r.capacity < total_hc:
        return f"capacité insuffisante ({r.capacity} places, {total_hc} requises)"
    if item.session_type:
        specific = [rt for rt in course.room_types if rt.startswith(item.session_type) and rt != item.session_type]
        req = specific if specific else [item.session_type]
    else:
        req = course.room_types
    if req and not any(rt in r.room_types for rt in req):
        return f"type incompatible (cours: {req}, salle: {r.room_types})"
    return "salle déjà occupée à ce créneau"


def _conflict_reason(item: ScheduleItem, day: int, hd: str, hf: str,
                     group_day_index, occ_teacher) -> str:
    """
    Retourne la première raison (groupe ou prof) pour laquelle item ne peut pas
    être placé à (day, hd, hf). Ne vérifie pas la salle — utile pour diagnostiquer
    pourquoi un échange de créneaux est impossible indépendamment du choix de salle.
    Retourne "ok" si aucun conflit groupe/prof détecté.
    """
    from bisect import bisect_left
    t1, t2 = hm(hd), hm(hf)
    for g in item.group:
        for gid in g.ancestors():
            minutes = group_day_index.get((gid, day), [])
            if minutes:
                if bisect_left(minutes, t1) < bisect_left(minutes, t2):
                    return f"groupe '{gid}' déjà occupé"
    for m in range(t1, t2):
        if (item.teacher.id, day, m) in occ_teacher:
            return f"prof '{item.teacher.name}' déjà occupé"
    return "ok"


# ===========================================================================
# SCÉNARIOS DE PERTURBATION
# ===========================================================================

# ===========================================================================
# SCÉNARIO PROF ABSENT
# ===========================================================================

def teacher_absent(
    schedule:         List[ScheduleItem],
    courses:          List[Course],
    rooms:            List[Room],
    nb_days:          int,
    teacher_id:       str,
    absent_intervals: AbsentIntervals,
    lunch_debut_min:  int,
    lunch_fin_min:    int,
    global_absent:    dict = None,
    soft_scorers:     Optional[ScorerList] = None,
    solver_timeout:   int = 60,
    min_day:          int = 0,
) -> Tuple[List[ScheduleItem], List[ScheduleItem], int, str, List[ScheduleItem], List[ScheduleItem]]:
    """
    Replanifie les cours d'un prof qui chevauche absent_intervals.
    absent_intervals : [(jour, heure_debut, heure_fin), ...]
    """
    valid_starts = _valid_starts_from(schedule)

    to_reschedule: List[ScheduleItem] = []
    fixed_schedule: List[ScheduleItem] = []

    for item in schedule:
        t1, t2 = hm(item.heure_debut), hm(item.heure_fin)
        overlaps = any(
            item.day == ad and t1 < hm(ah_fin) and hm(ah_debut) < t2
            for (ad, ah_debut, ah_fin) in absent_intervals
        )
        if item.teacher.id == teacher_id and overlaps and item.day >= basics.MIN_DAY:
            to_reschedule.append(item)
        else:
            fixed_schedule.append(item)

    n_attempted = len(to_reschedule)
    print(f"{n_attempted} session(s) à replanifier pour {teacher_id}.")

    new_schedule, cancelled, solver_status, rescheduled = resolve(
        to_reschedule=to_reschedule,
        fixed_schedule=fixed_schedule,
        courses=courses,
        rooms=rooms,
        nb_days=nb_days,
        valid_starts=valid_starts,
        absent_intervals=absent_intervals,
        lunch_debut_min=lunch_debut_min,
        lunch_fin_min=lunch_fin_min,
        global_absent = global_absent,
        soft_scorers=soft_scorers,
        solver_timeout=solver_timeout,
        min_day=min_day,
    )
    return new_schedule, cancelled, n_attempted, solver_status, rescheduled, to_reschedule


# ===========================================================================
# SCÉNARIO SALLE INDISPONIBLE
# ===========================================================================

def room_unavailable(
    schedule:         List[ScheduleItem],
    courses:          List[Course],
    rooms:            List[Room],
    nb_days:          int,
    room_name:        str,
    lunch_debut_min:  int,
    lunch_fin_min:    int,
    global_absent:    dict = None,
    absent_intervals: Optional[AbsentIntervals] = None,
    soft_scorers:     Optional[ScorerList]       = None,
    solver_timeout:   int = 60,
    min_day:          int = 0,
) -> Tuple[List[ScheduleItem], List[ScheduleItem], int, str, List[ScheduleItem], List[ScheduleItem]]:
    """
    Replanifie les sessions dont la salle est indisponible.
    absent_intervals=None → salle retirée de toute la semaine.
    """
    valid_starts = _valid_starts_from(schedule)

    all_absent: AbsentIntervals = (
        [(d, "00h00", "23h59") for d in range(nb_days)]
        if absent_intervals is None else absent_intervals
    )

    to_reschedule:  List[ScheduleItem] = []
    fixed_schedule: List[ScheduleItem] = []

    for item in schedule:
        t1, t2 = hm(item.heure_debut), hm(item.heure_fin)
        overlaps = any(
            item.day == ad and t1 < hm(ah_fin) and hm(ah_debut) < t2
            for (ad, ah_debut, ah_fin) in all_absent
        )
        if item.room == room_name and overlaps and item.day >= basics.MIN_DAY:
            to_reschedule.append(item)
        else:
            fixed_schedule.append(item)

    n_attempted = len(to_reschedule)
    print(f"{n_attempted} session(s) à changer de salle (salle {room_name!r} indisponible).")

    # Salle indisponible retirée du pool ; chaque cours reste sur son jour ET créneau d'origine
    rooms_ok     = [r for r in rooms if r.name != room_name]
    locked_slots = {id(item): (item.day, item.heure_debut) for item in to_reschedule}

    new_schedule, cancelled, solver_status, rescheduled = resolve(
        to_reschedule=to_reschedule,
        fixed_schedule=fixed_schedule,
        courses=courses,
        rooms=rooms_ok,
        nb_days=nb_days,
        valid_starts=valid_starts,
        absent_intervals=[],
        lunch_debut_min=lunch_debut_min,
        lunch_fin_min=lunch_fin_min,
        global_absent=global_absent,
        soft_scorers=soft_scorers,
        solver_timeout=solver_timeout,
        min_day=min_day,
        locked_slots=locked_slots,
    )
    return new_schedule, cancelled, n_attempted, solver_status, rescheduled, to_reschedule


# ===========================================================================
# SCÉNARIO LIBERATION DE CRENEAUX
# ===========================================================================

def free_slot(
    schedule:        List[ScheduleItem],
    courses:         List[Course],
    rooms:           List[Room],
    nb_days:         int,
    freed_intervals: AbsentIntervals,
    lunch_debut_min: int,
    lunch_fin_min:   int,
    global_absent:   dict = None,
    groups:          Optional[List[str]] = None,
    soft_scorers:    Optional[ScorerList] = None,
    solver_timeout:  int = 60,
    min_day:         int = 0,
) -> Tuple[List[ScheduleItem], List[ScheduleItem], int, str, List[ScheduleItem], List[ScheduleItem]]:
    """
    Libère des créneaux pour une liste de groupes, et replanifie leurs cours
    qui chevauchent freed_intervals.

    groups=None  → tous les groupes sont concernés (JPO, événement école...)
    groups=[...] → seulement ces groupes (filière, promo...)
    """
    valid_starts = _valid_starts_from(schedule)

    all_groups    = {g.id for item in schedule for g in item.group}
    target_groups = set(groups) if groups else all_groups
    global_free   = (target_groups == all_groups)

    to_reschedule:  List[ScheduleItem] = []
    fixed_schedule: List[ScheduleItem] = []

    for item in schedule:
        t1, t2 = hm(item.heure_debut), hm(item.heure_fin)
        overlaps = any(
            item.day == fd and t1 < hm(fh_fin) and hm(fh_debut) < t2
            for (fd, fh_debut, fh_fin) in freed_intervals
        )
        if any(g.id in target_groups for g in item.group) and overlaps and item.day >= basics.MIN_DAY:
            to_reschedule.append(item)
        else:
            fixed_schedule.append(item)

    n_attempted = len(to_reschedule)
    scope_str = "tous les groupes" if global_free else f"groupes {sorted(target_groups)}"
    print(f"{n_attempted} session(s) à replanifier ({scope_str}).")

    # Construire les absent_intervals pour le solver/greedy :
    # les groupes concernés ne peuvent pas être placés dans les freed_intervals.
    # Pour free_slot, on passe les freed_intervals comme absences ;
    # la restriction sera appliquée groupe par groupe dans is_valid_assignment.
    # Ici on passe freed_intervals directement et on laisse resolve filtrer.
    #
    # Pour les cas global_free (tous les groupes), on verrouille aussi
    # profs et salles dans l'occ de la fixed_schedule en ajoutant des items fantômes.
    # La façon la plus propre : injecter des ScheduleItem fictifs dans fixed_schedule.
    if global_free:
        all_teachers = set(item.teacher.id for item in schedule)
        all_rooms_   = set(item.room       for item in schedule if item.room != "?")

        # Créer des items fantômes pour bloquer profs et salles dans le solver
        for (fd, fh_debut, fh_fin) in freed_intervals:
            for tid in all_teachers:
                ghost_teacher = Teacher(id=tid, name="", courses=[])
                fixed_schedule.append(ScheduleItem(
                    course=-1, group=[], teacher=ghost_teacher,
                    day=fd, heure_debut=fh_debut, heure_fin=fh_fin, room="?",
                ))
            for rname in all_rooms_:
                ghost_teacher = Teacher(id="??", name="", courses=[])
                fixed_schedule.append(ScheduleItem(
                    course=-1, group=[], teacher=ghost_teacher,
                    day=fd, heure_debut=fh_debut, heure_fin=fh_fin, room=rname,
                ))

    new_schedule, cancelled, solver_status, rescheduled = resolve(
        to_reschedule=to_reschedule,
        fixed_schedule=fixed_schedule,
        courses=courses,
        rooms=rooms,
        nb_days=nb_days,
        valid_starts=valid_starts,
        absent_intervals=freed_intervals,
        lunch_debut_min=lunch_debut_min,
        lunch_fin_min=lunch_fin_min,
        global_absent=global_absent,
        soft_scorers=soft_scorers,
        solver_timeout=solver_timeout,
        min_day=min_day,
    )

    # Retirer les items fantômes du résultat final (ghosts ont course=-1,
    # ils sont dans fixed_schedule donc pas dans rescheduled)
    new_schedule = [it for it in new_schedule if it.course != -1]

    return new_schedule, cancelled, n_attempted, solver_status, rescheduled, to_reschedule


# ===========================================================================
# SCÉNARIO REMPLACEMENT
# ===========================================================================

def teacher_replacement(
    schedule:            List[ScheduleItem],
    courses:             List[Course],
    rooms:               List[Room],
    teachers:            List[Teacher],
    nb_days:             int,
    lunch_debut_min:     int,
    lunch_fin_min:       int,
    global_absent:       dict = None,
    absent_teacher_id:   Optional[str]            = None,
    target_course_ids:  Optional[List[int]]  = None,
    target_groups:       Optional[List[str]]       = None,
    target_session_type: Optional[str]             = None,
    absent_intervals:    Optional[AbsentIntervals] = None,
    soft_scorers:        Optional[ScorerList]      = None,
    solver_timeout:      int                       = 30,
) -> Tuple[List[ScheduleItem], List[ScheduleItem], int, str, List[dict]]:
    """
    Scénario Remplacement : trouve un ou plusieurs profs pour couvrir des cours
    dont l'enseignant est absent ou manquant.

    Le cours RESTE au même créneau et dans la même salle.
    On change uniquement le champ teacher de l'item.

    Paramètres :
      absent_teacher_id   : prof absent (ses cours sont à couvrir)
      target_course_ids   : filtre sur un cours par nom — liste de tous ses ids (un par groupe)
      target_groups       : filtre sur des groupes précis (ex: ["1_C", "1_G"])
      target_session_type : filtre sur un type de séance (ex: "TD", "CM", "TP")
      absent_intervals    : [(jour, hdebut, hfin), ...] — None = toute la semaine
      (absent_teacher_id ou target_course_id requis, les autres sont des affinations)
    """
    course_map = {c.id: c for c in courses}
    course_map.update({str(c.id): c for c in courses})

    # ------------------------------------------------------------------
    # 1. Identifier les instances à couvrir
    # ------------------------------------------------------------------
    affected: List[ScheduleItem] = []

    for item in schedule:
        t1, t2 = hm(item.heure_debut), hm(item.heure_fin)

        # Filtre prof absent
        if absent_teacher_id and item.teacher.id != absent_teacher_id:
            continue
        # Filtre cours par ids (tous les ids du même nom de cours, un par groupe)
        if target_course_ids and base_course_id(item.course) not in target_course_ids:
            continue
        # Filtre groupes
        if target_groups and not any(g.id in target_groups for g in item.group):
            continue
        # Filtre type de séance
        if target_session_type and item.session_type != target_session_type:
            continue
        # Filtre créneau
        if absent_intervals:
            overlaps = any(
                item.day == ad and t1 < hm(ah_fin) and hm(ah_debut) < t2
                for (ad, ah_debut, ah_fin) in absent_intervals
            )
            if not overlaps:
                continue
        if item.day < basics.MIN_DAY:
            continue

        affected.append(item)

    n_attempted = len(affected)
    print(f"  {n_attempted} instance(s) à couvrir.")

    if not affected:
        return list(schedule), [], 0, "OPTIMAL", []

    # Planning fixe = tout sauf les instances affectées (pour vérifier dispo/quota)
    affected_ids = set(id(item) for item in affected)
    fixed_schedule = [item for item in schedule if id(item) not in affected_ids]

    # ------------------------------------------------------------------
    # 2. Construire la liste de candidats pour chaque instance
    # ------------------------------------------------------------------
    candidates_per: List[List[Tuple[Teacher, float]]] = []
    for instance in affected:
        course = course_map.get(base_course_id(instance.course))
        cands  = find_candidates(instance, course, fixed_schedule, teachers, (global_absent or {}).get("teachers", {})) if course else []
        candidates_per.append(cands)
        if not cands:
            cname = course.name if course else str(instance.course)
            print(f"  [!] Aucun candidat pour '{cname}' ({fmt_abs_day(instance.day)} {instance.heure_debut}–{instance.heure_fin}) — détail :")
            if course:
                find_candidates(instance, course, fixed_schedule, teachers, (global_absent or {}).get("teachers", {}),verbose=True)
    # ------------------------------------------------------------------
    # 3. CP-SAT pour assigner les remplaçants
    # ------------------------------------------------------------------
    try:
        assignment, status = solve_replacement(
            affected, candidates_per, fixed_schedule, timeout=solver_timeout
        )
    except Exception as e:
        print(f"  → CP-SAT : EXCEPTION ({type(e).__name__}: {e}) — fallback greedy.")
        status     = f"EXCEPTION:{type(e).__name__}"
        assignment = {}

    if status not in ("OPTIMAL", "FEASIBLE"):
        # Fallback greedy : on prend le meilleur candidat disponible pour chaque instance
        print(f"  → CP-SAT : {status} — fallback greedy.")
        assignment = {}
        used: dict = defaultdict(float)   # t_id → heures déjà assignées ce run
        for i, (instance, cands) in enumerate(zip(affected, candidates_per)):
            for teacher, adequacy in cands:
                dur_h = (hm(instance.heure_fin) - hm(instance.heure_debut)) / 60.0
                rem   = remaining_hours(teacher, fixed_schedule) - used[teacher.id]
                if rem >= dur_h:
                    assignment[i] = (teacher, adequacy)
                    used[teacher.id] += dur_h
                    break
        status = "GREEDY"
    else:
        print(f"  → CP-SAT : {status}")

    # ------------------------------------------------------------------
    # 4. Construire le nouveau planning et le log
    # ------------------------------------------------------------------
    new_schedule   = list(fixed_schedule)
    unresolved     = []
    assignment_log = []

    for i, instance in enumerate(affected):
        course = course_map.get(base_course_id(instance.course))
        cname  = course.name if course else str(instance.course)
        jour   = fmt_abs_day(instance.day)

        if i in assignment:
            new_teacher, adequacy = assignment[i]
            new_item = instance._replace(teacher=new_teacher)
            new_schedule.append(new_item)
            print(f"  ✓ {cname} — {[g.id for g in instance.group]} ({jour} {instance.heure_debut}–{instance.heure_fin}) "
                  f"→ {new_teacher.name} [adéquation={adequacy:.2f}]")
            assignment_log.append({
                "course":            cname,
                "group":             instance.group,
                "day":               instance.day,
                "heure_debut":       instance.heure_debut,
                "heure_fin":         instance.heure_fin,
                "original_teacher":  instance.teacher.name,
                "original_teacher_id": instance.teacher.id,
                "replacement":       new_teacher.name,
                "replacement_id":    new_teacher.id,
                "adequacy":          adequacy,
            })
        else:
            unresolved.append(instance)
            print(f"  ✗ {cname} — {instance.group} ({jour} {instance.heure_debut}–{instance.heure_fin}) "
                  f"— aucun remplaçant disponible")
            assignment_log.append({
                "course":            cname,
                "group":             instance.group,
                "day":               instance.day,
                "heure_debut":       instance.heure_debut,
                "heure_fin":         instance.heure_fin,
                "original_teacher":  instance.teacher.name,
                "original_teacher_id": instance.teacher.id,
                "replacement":       None,
                "replacement_id":    None,
                "adequacy":          None,
            })

    if unresolved and status in ("OPTIMAL", "FEASIBLE", "GREEDY"):
        status = "PARTIAL"
    return new_schedule, unresolved, n_attempted, status, assignment_log


# ===========================================================================
# SCÉNARIO DEPLACEMENT DE COURS
# ===========================================================================
def get_slot(candidates: List[Tuple], day: int) -> Optional[int]:
    """
    Interaction console : affiche les créneaux candidats et laisse l'utilisateur
    choisir. Retourne l'index du candidat choisi, ou None si l'utilisateur annule.
    Signature compatible avec slot_picker_fn de move().
    """
    print(f"\nCréneaux disponibles {fmt_abs_day(day)} :")
    for i, can in enumerate(candidates):
        print(f"  [{i+1}] {can[4]}–{can[5]}  salle {can[6].name}  (score = {can[0]:.4f})")
    choix = input(">>> Numéro du créneau choisi (rien pour annuler) > ").strip()
    if choix.isdigit() and 1 <= int(choix) <= len(candidates):
        return int(choix) - 1
    return None


def _best_slot(candidates: List[Tuple], day: int) -> Optional[int]:
    """Choisit automatiquement le meilleur candidat (index 0, déjà trié).
    Passé comme slot_picker_fn dans full_solve pour éviter toute interaction console."""
    return 0 if candidates else None


def move_one(
        schedule: List[ScheduleItem],
        to_move: ScheduleItem,
        lunch_debut_min: int,
        lunch_fin_min:   int,
        day: int,
        valid_starts: List[int],
        courses: List[Course],
        rooms: List[Room],
        heure_debut: Optional[str] = None,
        soft_scorers: Optional[ScorerList] = None,
        slot_picker_fn=None,
        keep_room: bool = False,
        global_absent: dict = {},
        ) -> Tuple[List[ScheduleItem], bool, Optional[ScheduleItem]]:
    """
    Déplace un cours (to_move) vers un nouveau créneau du jour day.

    Deux modes :
      - Créneau précis (heure_debut valide) : placement direct.
      - Jour seul (ou créneau précis invalide) : liste les créneaux valides du jour,
        les trie par score, délègue le choix à slot_picker_fn.

    slot_picker_fn(candidates, day) -> Optional[int] :
      - get_slot   : interaction console, l'utilisateur choisit (mode interactif)
      - _best_slot : choisit automatiquement le meilleur score (mode full_solve)
      Si None, utilise get_slot par défaut.

    Retourne (new_schedule, done, placed_item) :
      - new_schedule : planning mis à jour (inchangé si déplacement impossible)
      - done         : True si le cours a été déplacé, False sinon
      - placed_item  : le ScheduleItem nouvellement inséré (None si done=False)
    """
    picker       = slot_picker_fn if slot_picker_fn is not None else get_slot
    new_schedule = list(schedule)
    ok           = False
    done         = False
    placed_item  = None

    if to_move.day < basics.MIN_DAY:
        return schedule, None, None   # item passé : ignoré silencieusement

    nb_blocked_teacher = {}
    nb_blocked_group = {}
    nb_blocked_room = {}

    for item in schedule:
        if item != to_move:
            continue

        nb_blocked_teacher[id(item)] = 0
        nb_blocked_group[id(item)] = 0
        nb_blocked_room[id(item)] = 0
        
        ok = True
        new_schedule.remove(item)
        group_day_index, occ_room, occ_teacher = build_occupations(new_schedule)

        course_map = {c.id: c for c in courses}
        course     = course_map[base_course_id(item.course)]
        room_map   = {r.name: r for r in rooms}
        room       = room_map[item.room]

        duration  = hm(item.heure_fin) - hm(item.heure_debut)

        # --- Créneau précis fourni et valide → placement direct ---
        if heure_debut is not None:
            heure_fin = min_to_hm(hm(heure_debut) + duration)
            if is_valid_assignment_with_blocked(to_move, course, day, heure_debut, heure_fin, room,
                                   [], lunch_debut_min, lunch_fin_min,
                                   group_day_index, occ_room, occ_teacher, (global_absent or {}).get("teachers", {}), (global_absent or {}).get("groups",{}), (global_absent or {}).get("rooms",{})):
                placed_item = to_move._replace(day=day, heure_debut=heure_debut, heure_fin=heure_fin)
                new_schedule.append(placed_item)
                done = True

        if not done:
            # --- Jour seul (ou créneau précis invalide) → lister les candidats ---
            scorers       = soft_scorers or []
            candidates    = []
            rooms_to_try  = [room] if keep_room else rooms

            for start_min in valid_starts:
                hd = min_to_hm(start_min)
                hf = min_to_hm(start_min + duration)
                end_min = start_min + duration
                for r in rooms_to_try:

                    blocked = False
                    for (abd, abh, abf) in (global_absent or {}).get("teachers", {}).get(item.teacher.id, []):
                        if abd == day and start_min < hm(abf) and hm(abh) < end_min:
                            blocked = True; nb_blocked_teacher[id(item)] += 1; break
                    if not blocked:
                        for g in item.group:
                            for (abd, abh, abf) in (global_absent or {}).get("groups", {}).get(g.id, []):
                                if abd == day and start_min < hm(abf) and hm(abh) < end_min:
                                    blocked = True; nb_blocked_group[id(item)] += 1; break
                            if blocked: break
                    if not blocked:
                        for (abd, abh, abf) in (global_absent or {}).get("rooms", {}).get(r.name, []):
                            if abd == day and start_min < hm(abf) and hm(abh) < end_min:
                                blocked = True; nb_blocked_room[id(item)] += 1; break
                    if blocked:
                        continue

                    if not is_valid_assignment(item, course, day, hd, hf, r,
                                               [], lunch_debut_min, lunch_fin_min,
                                               group_day_index, occ_room, occ_teacher,):
                        continue
                    soft_penalty = sum(
                        w * fn(item, course, day, hd, hf, r,
                               group_day_index, occ_teacher, lunch_debut_min, lunch_fin_min)
                        for fn, w in scorers
                    )
                    room_fit = (r.capacity - sum(g.headcount for g in item.group)) / max(r.capacity, 1)
                    candidates.append((soft_penalty, room_fit, day, start_min, hd, hf, r))

            if not candidates:
                reason = []
                if nb_blocked_teacher.get(id(item), 0) > 0 : reason.append(f"Aucun créneau avec un professeur disponible")
                if nb_blocked_group.get(id(item), 0) > 0 : reason.append(f"Aucun créneau où le groupe est disponible")
                if nb_blocked_room.get(id(item), 0) > 0 : reason.append(f"Aucun créneau avec une salle disponible")
                print(f"  [!] Aucun placement valide pour {item.course} {', '.join([g.id for g in item.group])} ({fmt_abs_day(item.day)}, {item.heure_debut}-{item.heure_fin} — {', '.join(reason) if reason else 'contraintes planning'}")
                new_schedule.append(to_move)  # on remet le cours en place
            else:
                candidates.sort(key=lambda c: (c[0], c[1], c[2], c[3]))
                choice = picker(candidates, day)
                if choice is not None:
                    _, _, _, _, hd, hf, r = candidates[choice]
                    placed_item = to_move._replace(day=day, heure_debut=hd, heure_fin=hf, room=r.name, building=r.bat)
                    new_schedule.append(placed_item)
                    done = True
                else:
                    new_schedule.append(to_move)  # l'utilisateur a annulé
        break  # on a trouvé et traité to_move, inutile de continuer

    if not ok:
        print(f"  [!] Cours non trouvé dans le planning.")

    return new_schedule, done, placed_item

def move_all(
        schedule: List[ScheduleItem],
        to_move: List[Tuple[ScheduleItem, int, Optional[str]]],
        nb_days: int,
        lunch_debut_min: int,
        lunch_fin_min:   int,
        valid_starts: List[int],
        courses: List[Course],
        rooms: List[Room],
        soft_scorers: Optional[ScorerList] = None,
        slot_picker_fn=None,
        keep_room: bool = False,
        solver_timeout: int = 60,
        global_absent: dict = {},
        ) -> Tuple[List[ScheduleItem], bool, int, List[Optional[ScheduleItem]]]:
    """
    Déplace une liste de cours vers leurs jours cibles en une passe :
    retire tous les items d'abord, puis les replace séquentiellement.

    to_move : [(item, target_day, heure_debut_optionnelle), ...]

    Retourne (new_schedule, all_done, nb_done, placed_items) :
      - all_done     : True si tous les items ont été placés
      - nb_done      : nombre d'items effectivement placés
      - placed_items : ScheduleItem placé (ou None) pour chaque item de to_place, dans l'ordre
    """

    #----------------------------------------------------------------------------------------
    # 1. Identifier les cours existants dans l'emploi du temps donné
    #----------------------------------------------------------------------------------------
    new_schedule = list(schedule)

    to_place = []
    not_found = []

    to_move_fr = [tup for tup in to_move if tup[0].day >= basics.MIN_DAY]

    for item, day, heure_debut in to_move_fr:
        if item not in new_schedule:
            print(f"Cours {item.course} du groupe {item.group} ({fmt_abs_day(item.day)}, {item.heure_debut}-{item.heure_fin} introuvable)")
            not_found.append(item)
        else:
            new_schedule.remove(item)
            to_place.append((item, day, heure_debut))
    prompt = f"Nous devons déplacer {len(to_place)} cours ({len(not_found)} cours non trouvés)" if len(not_found)!=0 else f"Nous devons déplacer {len(to_place)} cours"
    print(prompt)

    #----------------------------------------------------------------------------------------
    # 2. CP-SAT
    #----------------------------------------------------------------------------------------
    new_schedule, cancelled_items, moved_items, status = solve_move_all(to_place, new_schedule, courses, rooms, nb_days, valid_starts, lunch_debut_min, lunch_fin_min, global_absent, soft_scorers, solver_timeout)

    #----------------------------------------------------------------------------------------
    # 3. Fallback greedy
    #----------------------------------------------------------------------------------------

    if status not in ("OPTIMAL", "FEASIBLE"):
        # Fallback greedy : on prend le meilleur candidat disponible pour chaque instance
        print(f"  → CP-SAT : {status} — fallback greedy.")

        nb_done = 0
        placed_items = []
        for item, day, heure_debut in to_place:
            new_schedule.append(item)   # move_one a besoin de trouver l'item pour le retirer
            new_schedule, done, placed_item = move_one(new_schedule, item, lunch_debut_min, lunch_fin_min, day, valid_starts, courses, rooms, heure_debut, soft_scorers, slot_picker_fn, keep_room, global_absent=global_absent)
            if  done is not None:
                nb_done += 1*done
                placed_items.append(placed_item)
        all_done = len(to_place)==nb_done
        status = "GREEDY"
    else:
        # Aligner placed_items avec to_place (None pour les cours non placés)
        cancelled_set = {id(c) for c in cancelled_items}
        moved_iter    = iter(moved_items)
        placed_items  = []
        for item, _, _ in to_place:
            if id(item) in cancelled_set:
                new_schedule.append(item)  # remettre le cours annulé à sa place
                placed_items.append(None)
            else:
                placed_items.append(next(moved_iter, None))
        all_done = len(cancelled_items) == 0
        nb_done  = len(to_place) - len(cancelled_items)
        if not all_done:
            print(f"  → CP-SAT : {status} ({nb_done}/{len(to_place)} déplacés) — {len(cancelled_items)} cours remis à leur place originale.")
        else:
            print(f"  → CP-SAT : {status} — tous les cours déplacés.")
    
    return new_schedule, all_done, nb_done, placed_items


# ===========================================================================
# SCÉNARIO PERMUTATION DE COURS
# ===========================================================================

def permutation(
        schedule: List[ScheduleItem],
        perm1: ScheduleItem,
        perm2: ScheduleItem,
        lunch_debut_min: int,
        lunch_fin_min:   int,
        valid_starts: List[int],
        courses: List[Course],
        rooms: List[Room],
        soft_scorers: Optional[ScorerList] = None,
        slot_picker_fn=None,
        keep_room: bool = False,
        move_courses: bool = True,
        global_absent: dict = {},
        ) -> Tuple[List[ScheduleItem], bool, List[ScheduleItem]]:
    """
    [!] A COMPLETER
    """
    picker       = slot_picker_fn if slot_picker_fn is not None else get_slot
    new_schedule = list(schedule)
    ok           = False
    done         = False
    placed_items  = []

    if perm1.day < basics.MIN_DAY or perm2.day < basics.MIN_DAY:
        return schedule, None, None   # item(s) passé(s) : ignoré silencieusement

    def _find_remove(sched, item):
        for i, it in enumerate(sched):
            if (it.course == item.course
                    and it.day == item.day
                    and it.heure_debut == item.heure_debut
                    and [g.id for g in it.group] == [g.id for g in item.group]):
                return sched[:i] + sched[i+1:], True
        return sched, False

    new_schedule, found1 = _find_remove(new_schedule, perm1)
    if not found1:
        print(f"  [!] Cours 1 non trouvé dans le planning.")
        return list(schedule), False, []

    new_schedule, found2 = _find_remove(new_schedule, perm2)
    if not found2:
        print(f"  [!] Cours 2 non trouvé dans le planning.")
        return list(schedule), False, []

    ok = True

    duration1 = hm(perm1.heure_fin)-hm(perm1.heure_debut)
    duration2 = hm(perm2.heure_fin)-hm(perm2.heure_debut)
    if duration1 != duration2:
        print(f"  [!] Durées différentes ({duration1} min / {duration2} min) — vérification des créneaux en cours...")

    group_day_index, occ_room, occ_teacher = build_occupations(new_schedule)

    course_map = {c.id: c for c in courses}
    course1     = course_map[base_course_id(perm1.course)]
    course2     = course_map[base_course_id(perm2.course)]
    room_map   = {r.name: r for r in rooms}
    room1       = room_map[perm1.room]
    room2       = room_map[perm2.room]

    if keep_room:
        ok1 = is_valid_assignment_with_blocked(perm1, course1, perm2.day, perm2.heure_debut, min_to_hm(hm(perm2.heure_debut)+duration1), room1,
                                               [], lunch_debut_min, lunch_fin_min,
                                               group_day_index, occ_room, occ_teacher, teacher_blocked=(global_absent or {}).get("teachers",{}), groups_blocked=(global_absent or {}).get("groups",{}), rooms_blocked=(global_absent or {}).get("rooms",{}))
        ok2 = is_valid_assignment_with_blocked(perm2, course2, perm1.day, perm1.heure_debut, min_to_hm(hm(perm1.heure_debut)+duration2), room2,
                                               [], lunch_debut_min, lunch_fin_min,
                                               group_day_index, occ_room, occ_teacher, teacher_blocked=(global_absent or {}).get("teachers",{}), groups_blocked=(global_absent or {}).get("groups",{}), rooms_blocked=(global_absent or {}).get("rooms",{}))
        if ok1 and ok2:
            placed_items.append(perm1._replace(day=perm2.day, heure_debut=perm2.heure_debut, heure_fin=min_to_hm(hm(perm2.heure_debut)+duration1)))
            placed_items.append(perm2._replace(day=perm1.day, heure_debut=perm1.heure_debut, heure_fin=min_to_hm(hm(perm1.heure_debut)+duration2)))
            new_schedule.extend(placed_items)
            ok = True
            done = True
        else:
            if not ok1 and not ok2:
                r1_reason = _conflict_reason(perm1, perm2.day, perm2.heure_debut, perm2.heure_fin, group_day_index, occ_teacher)
                r2_reason = _conflict_reason(perm2, perm1.day, perm1.heure_debut, perm1.heure_fin, group_day_index, occ_teacher)
                print(f"  [!] Échange impossible dans les deux sens :"
                      f"\n      '{course1.name}' → {fmt_abs_day(perm2.day)} {perm2.heure_debut} : {r1_reason}"
                      f"\n      '{course2.name}' → {fmt_abs_day(perm1.day)} {perm1.heure_debut} : {r2_reason}")
                if move_courses:
                    print(f"  [!] Tentative de déplacement individuel...")
                    new_schedule, done1, placed_item = move_one(schedule, perm1, lunch_debut_min, lunch_fin_min, perm2.day, valid_starts, courses, rooms, soft_scorers=soft_scorers, slot_picker_fn=_best_slot, global_absent=global_absent)
                    placed_items.append(placed_item)
                    new_schedule, done2, placed_item = move_one(new_schedule, perm2, lunch_debut_min, lunch_fin_min, perm1.day, valid_starts, courses, rooms, soft_scorers=soft_scorers, slot_picker_fn=_best_slot, global_absent=global_absent)
                    placed_items.append(placed_item)
                    if not done1:
                        print(f"  [!] Déplacement de '{course1.name}' vers {fmt_abs_day(perm2.day)} impossible.")
                    if not done2:
                        print(f"  [!] Déplacement de '{course2.name}' vers {fmt_abs_day(perm1.day)} impossible.")
                    done = done1 and done2
                    ok = True
            elif ok1 and not ok2:
                r2_reason = _conflict_reason(perm2, perm1.day, perm1.heure_debut, perm1.heure_fin, group_day_index, occ_teacher)
                print(f"  [!] '{course2.name}' ne peut pas aller à {fmt_abs_day(perm1.day)} {perm1.heure_debut} : {r2_reason}")
                if move_courses:
                    print(f"  [!] Tentative de déplacement individuel de '{course2.name}'...")
                    new_schedule, done, placed_item = move_one(schedule, perm2, lunch_debut_min, lunch_fin_min, perm1.day, valid_starts, courses, rooms, soft_scorers=soft_scorers, slot_picker_fn=_best_slot, global_absent=global_absent)
                    placed_items.append(placed_item)
                    if not done:
                        print(f"  [!] Déplacement de '{course2.name}' vers {fmt_abs_day(perm1.day)} impossible.")
                    ok = True
            else:
                r1_reason = _conflict_reason(perm1, perm2.day, perm2.heure_debut, perm2.heure_fin, group_day_index, occ_teacher)
                print(f"  [!] '{course1.name}' ne peut pas aller à {fmt_abs_day(perm2.day)} {perm2.heure_debut} : {r1_reason}")
                if move_courses:
                    print(f"  [!] Tentative de déplacement individuel de '{course1.name}'...")
                    new_schedule, done, placed_item = move_one(schedule, perm1, lunch_debut_min, lunch_fin_min, perm2.day, valid_starts, courses, rooms, soft_scorers=soft_scorers, slot_picker_fn=_best_slot, global_absent=global_absent)
                    placed_items.append(placed_item)
                    if not done:
                        print(f"  [!] Déplacement de '{course1.name}' vers {fmt_abs_day(perm2.day)} impossible.")
                    ok = True
    else:
        scorers = soft_scorers or []
        pairs   = []
        for r1 in rooms:
            for r2 in rooms:
                ok1 = is_valid_assignment_with_blocked(perm1, course1, perm2.day, perm2.heure_debut, min_to_hm(hm(perm2.heure_debut)+duration1), r1,
                                          [], lunch_debut_min, lunch_fin_min,
                                          group_day_index, occ_room, occ_teacher, teacher_blocked=(global_absent or {}).get("teachers",{}), groups_blocked=(global_absent or {}).get("groups",{}), rooms_blocked=(global_absent or {}).get("rooms",{}))
                ok2 = is_valid_assignment_with_blocked(perm2, course2, perm1.day, perm1.heure_debut, min_to_hm(hm(perm1.heure_debut)+duration2), r2,
                                          [], lunch_debut_min, lunch_fin_min,
                                          group_day_index, occ_room, occ_teacher, teacher_blocked=(global_absent or {}).get("teachers",{}), groups_blocked=(global_absent or {}).get("groups",{}), rooms_blocked=(global_absent or {}).get("rooms",{}))
                if ok1 and ok2:
                    sp1 = sum(w * fn(perm1, course1, perm2.day, perm2.heure_debut, min_to_hm(hm(perm2.heure_debut)+duration1), r1,
                                     group_day_index, occ_teacher, lunch_debut_min, lunch_fin_min)
                              for fn, w in scorers)
                    sp2 = sum(w * fn(perm2, course2, perm1.day, perm1.heure_debut, min_to_hm(hm(perm1.heure_debut)+duration2), r2,
                                     group_day_index, occ_teacher, lunch_debut_min, lunch_fin_min)
                              for fn, w in scorers)
                    rf1 = (r1.capacity - sum(g.headcount for g in perm1.group)) / max(r1.capacity, 1)
                    rf2 = (r2.capacity - sum(g.headcount for g in perm2.group)) / max(r2.capacity, 1)
                    pairs.append((sp1 + sp2, rf1 + rf2, r1, r2))

        if pairs:
            pairs.sort(key=lambda p: (p[0], p[1]))
            _, _, r1, r2 = pairs[0]
            placed_items.append(perm1._replace(day=perm2.day, heure_debut=perm2.heure_debut, heure_fin=min_to_hm(hm(perm2.heure_debut)+duration1), room=r1.name))
            placed_items.append(perm2._replace(day=perm1.day, heure_debut=perm1.heure_debut, heure_fin=min_to_hm(hm(perm1.heure_debut)+duration2), room=r2.name))
            new_schedule.extend(placed_items)
            ok   = True
            done = True
        else:
            hf1 = min_to_hm(hm(perm2.heure_debut) + duration1)
            hf2 = min_to_hm(hm(perm1.heure_debut) + duration2)
            r1_reason = _conflict_reason(perm1, perm2.day, perm2.heure_debut, hf1, group_day_index, occ_teacher)
            r2_reason = _conflict_reason(perm2, perm1.day, perm1.heure_debut, hf2, group_day_index, occ_teacher)
            if move_courses:
                print(f"  [!] Échange direct impossible :"
                      f"\n      '{course1.name}' → {fmt_abs_day(perm2.day)} {perm2.heure_debut}–{hf1} : {r1_reason}"
                      f"\n      '{course2.name}' → {fmt_abs_day(perm1.day)} {perm1.heure_debut}–{hf2} : {r2_reason}"
                      f"\n  Tentative de déplacement individuel...")
                new_schedule, done1, pi1 = move_one(schedule, perm1, lunch_debut_min, lunch_fin_min, perm2.day, valid_starts, courses, rooms, soft_scorers=soft_scorers, slot_picker_fn=_best_slot, global_absent=global_absent)
                placed_items.append(pi1)
                new_schedule, done2, pi2 = move_one(new_schedule, perm2, lunch_debut_min, lunch_fin_min, perm1.day, valid_starts, courses, rooms, soft_scorers=soft_scorers, slot_picker_fn=_best_slot, global_absent=global_absent)
                placed_items.append(pi2)
                done = done1 and done2
                if not done1:
                    print(f"  [!] Déplacement de '{course1.name}' vers {fmt_abs_day(perm2.day)} impossible.")
                if not done2:
                    print(f"  [!] Déplacement de '{course2.name}' vers {fmt_abs_day(perm1.day)} impossible.")
                ok = True
            else:
                print(f"  [!] Échange direct impossible :"
                      f"\n      '{course1.name}' → {fmt_abs_day(perm2.day)} {perm2.heure_debut}–{hf1} : {r1_reason}"
                      f"\n      '{course2.name}' → {fmt_abs_day(perm1.day)} {perm1.heure_debut}–{hf2} : {r2_reason}")

    if not done:
        new_schedule = list(schedule)

    return new_schedule, done, placed_items


# ===========================================================================
# SCÉNARIO CHANGEMENT DE SALLE
# ===========================================================================

def all_room_change(
        schedule: List[ScheduleItem],
        to_change: List[Tuple],   # (item,) | (item, room_name, best_room)
        lunch_debut_min: int,
        lunch_fin_min:   int,
        courses: List[Course],
        rooms: List[Room],
        soft_scorers: Optional[ScorerList] = None,
        solver_timeout: int = 60,
        global_absent: dict = {},
        ) -> Tuple[List[ScheduleItem], List[ScheduleItem], List[ScheduleItem], str, List[ScheduleItem], List[ScheduleItem]]:
    """
    Retourne (new_schedule, exact_items, moved_items, status, not_done, specific_not_done).
      exact_items      : salle demandée attribuée directement
      moved_items      : meilleure salle trouvée par CP-SAT/greedy (peut être la salle d'origine)
      not_done         : aucune salle valide (envoyés en CP-SAT/greedy)
      specific_not_done: salle précise indisponible et best_room=False
    """
    new_schedule = list(schedule)

    to_change_fr = [tup for tup in to_change if tup[0].day >= basics.MIN_DAY]

    for tup in to_change_fr:
        new_schedule.remove(tup[0])

    exact_items = []        # salle demandée obtenue directement
    to_place = []           # envoyés en CP-SAT / greedy (meilleure salle)
    specific_not_done = []  # salle précise rejetée + best_room=False

    group_day_index, occ_room, occ_teacher = build_occupations(new_schedule)

    courses_map = {c.id: c for c in courses}
    room_map = {r.name: r for r in rooms}

    for tup in to_change_fr:
        item = tup[0]
        if len(tup) == 3:
            room_name, best_room = tup[1], tup[2]
            ok = is_valid_assignment(
                item, courses_map[base_course_id(item.course)],
                item.day, item.heure_debut, item.heure_fin,
                room_map[room_name], [],
                lunch_debut_min, lunch_fin_min,
                group_day_index, occ_room, occ_teacher,
            )
            if ok:
                new_item = item._replace(room=room_name, building=room_map[room_name].bat)
                new_schedule.append(new_item)
                exact_items.append(new_item)
            elif best_room:
                to_place.append(item)
                reason = _room_reject_reason(item, room_name, courses_map[base_course_id(item.course)], room_map)
                print(f"  ~ '{item.course}' [{', '.join(g.id for g in item.group)}] {item.heure_debut}–{item.heure_fin} : salle {room_name} indisponible ({reason}) — recherche meilleure salle...")
            else:
                specific_not_done.append(item)
                reason = _room_reject_reason(item, room_name, courses_map[base_course_id(item.course)], room_map)
                print(f"  ✗ '{item.course}' [{', '.join(g.id for g in item.group)}] {item.heure_debut}–{item.heure_fin} : salle {room_name} indisponible ({reason}), remis en place.")
        else:
            to_place.append(item)

    cp_result, not_done, moved_items, status = solve_all_room_change(
        to_place, new_schedule, courses, rooms,
        lunch_debut_min, lunch_fin_min, global_absent, soft_scorers, solver_timeout,
    )

    if status not in ("OPTIMAL", "FEASIBLE"):
        print(f"  → CP-SAT : {status} — fallback greedy.")
        status = "GREEDY"
        scorers = soft_scorers or []

        nb_blocked_teacher = {}
        nb_blocked_group = {}
        nb_blocked_room = {}

        for item in to_place:

            nb_blocked_teacher[id(item)] = 0
            nb_blocked_group[id(item)] = 0
            nb_blocked_room[id(item)] = 0

            group_day_index, occ_room, occ_teacher = build_occupations(new_schedule)
            course = courses_map[base_course_id(item.course)]

            candidates = []
            for r in rooms:
                blocked = False
                for (abd, abh, abf) in (global_absent or {}).get("teachers", {}).get(item.teacher.id, []):
                    if abd == item.day and hm(item.heure_debut) < hm(abf) and hm(abh) < hm(item.heure_fin):
                        blocked = True; nb_blocked_teacher[id(item)] += 1; break
                if not blocked:
                    for g in item.group:
                        for (abd, abh, abf) in (global_absent or {}).get("groups", {}).get(g.id, []):
                            if abd == item.day and hm(item.heure_debut) < hm(abf) and hm(abh) < hm(item.heure_fin):
                                blocked = True; nb_blocked_group[id(item)] += 1; break
                        if blocked: break
                if not blocked:
                    for (abd, abh, abf) in (global_absent or {}).get("rooms", {}).get(r.name, []):
                        if abd == item.day and hm(item.heure_debut) < hm(abf) and hm(abh) < hm(item.heure_fin):
                            blocked = True; nb_blocked_room[id(item)] += 1; break
                if blocked:
                    continue


                if not is_valid_assignment(item, course,
                                           item.day, item.heure_debut, item.heure_fin, r,
                                           [], lunch_debut_min, lunch_fin_min,
                                           group_day_index, occ_room, occ_teacher):
                    continue
                soft_penalty = sum(
                    w * fn(item, course, item.day, item.heure_debut, item.heure_fin, r,
                           group_day_index, occ_teacher, lunch_debut_min, lunch_fin_min)
                    for fn, w in scorers
                )
                candidates.append((soft_penalty, r))

            if not candidates:
                reason = []
                if nb_blocked_teacher.get(id(item), 0) > 0 : reason.append(f"Aucun créneau avec un professeur disponible")
                if nb_blocked_group.get(id(item), 0) > 0 : reason.append(f"Aucun créneau où le groupe est disponible")
                if nb_blocked_room.get(id(item), 0) > 0 : reason.append(f"Aucun créneau avec une salle disponible")
                print(f"  [!] Aucun placement valide pour {item.course} {', '.join([g.id for g in item.group])} ({fmt_abs_day(item.day)}, {item.heure_debut}-{item.heure_fin} — {', '.join(reason) if reason else 'contraintes planning'}")
                
                not_done.append(item)
            else:
                candidates.sort(key=lambda c: c[0])
                new_item = item._replace(room=candidates[0][1].name, building=candidates[0][1].bat)
                new_schedule.append(new_item)
                moved_items.append(new_item)
    else:
        new_schedule = cp_result

    return new_schedule, exact_items, moved_items, status, not_done, specific_not_done


# ===========================================================================
# SCÉNARIO AJOUTER UNE SESSION D'UN COURS EXISTANT
# ===========================================================================
def add_sessions(
        schedule: List[ScheduleItem],
        to_add: List[Tuple[Course, Teacher, List[Group], str, int, Optional[int], Optional[int], Optional[Room], Optional[str]]],   # (course,teacher,group,session_type,duration) | (course,teacher,group,session_type,duration,week,day,room,heure_debut)
        lunch_debut_min: int,
        lunch_fin_min:   int,
        nb_days: int,
        courses: List[Course],
        rooms: List[Room],
        soft_scorers: Optional[ScorerList] = None,
        solver_timeout: int = 60,
        global_absent: dict = {},
    ) -> Tuple[List[ScheduleItem], List[ScheduleItem], List[ScheduleItem], str, List[ScheduleItem], List[ScheduleItem]]:
    """
    [!] A COMPLETER // AJOUTER UNE SESSION D'UN COURS DEJA EXISTANT!!!! (donc pas de récurrence, et course est deja dans courses!)
    """
    valid_starts = _valid_starts_from(schedule)
    new_schedule = list(schedule)
    done = []
    not_done = []
    to_place = []
    course_map = {c.id: c for c in courses}
    room_map = {r.name: r for r in rooms}

    for tup in to_add:
        course = tup[0].id; teach = tup[1]; groups = tup[2] if isinstance(tup[2], list) else [tup[2]]; session_type = tup[3]; duration = tup[4]
        week = tup[5] if isinstance(tup[5], int) else None; day = tup[6] if isinstance(tup[6], int) else None; day_abs = to_abs_day(week,day) if (week is not None and day is not None) else None
        room = None if tup[7] is None else tup[7].name
        bat = None if tup[7] is None else tup[7].bat
        heure_debut = None if not tup[8] else tup[8]
        heure_fin = None if not tup[8] else min_to_hm(hm(tup[8])+duration)

        if day_abs is not None and day_abs < basics.MIN_DAY:
            print(f"  ✗ Impossible de placer '{tup[0].name}' [{[g.id for g in groups]}] ({fmt_abs_day(day_abs)}): la date demandée est déjà passée")
            continue

        it = ScheduleItem(course, groups, teach, day_abs, heure_debut, heure_fin, room, bat, session_type)

        locked_info = {}
        locked_info["days"]=None
        locked_info["weeks"]=None
        locked_info["room"]=None
        locked_info["hd"]=None

        if day_abs is not None:
            locked_info["days"] = day_abs
        else:
            if week is not None:
                locked_info["weeks"] = [to_abs_day(week,i) for i in range(5)]
        if room is not None:
            locked_info["room"] = tup[7]
        if heure_debut is not None:
            locked_info["hd"] = heure_debut

        to_place.append((it, duration, locked_info))

    schedule_solver, cancelled_items, placed_items, status = solve_all_add_sessions(to_place, new_schedule, courses, rooms, nb_days, valid_starts, lunch_debut_min, lunch_fin_min, global_absent, soft_scorers, solver_timeout)

    if status not in ("OPTIMAL", "FEASIBLE"):
        print(f"  → CP-SAT : {status} — fallback greedy.")
        status = "GREEDY"
        scorers = soft_scorers or []
        valid_starts = _valid_starts_from(schedule)

        nb_blocked_teacher = {}
        nb_blocked_group = {}
        nb_blocked_room = {}

        for item, duration, locked_info in to_place:
            group_day_index, occ_room, occ_teacher = build_occupations(new_schedule)
            course_obj = course_map[base_course_id(item.course)]

            # Pré-filtrer les espaces de recherche
            if locked_info["days"] is not None:
                days_range = [locked_info["days"]]
            elif locked_info["weeks"] is not None:
                days_range = locked_info["weeks"]
            else:
                days_range = range(nb_days)

            rooms_range = [locked_info["room"]] if locked_info["room"] is not None else rooms
            starts_range = [hm(locked_info["hd"])] if locked_info["hd"] is not None else valid_starts

            nb_blocked_teacher[id(item)] = 0
            nb_blocked_group[id(item)] = 0
            nb_blocked_room[id(item)] = 0

            candidates = []
            for d in days_range:
                for r in rooms_range:
                    for start_min in starts_range:
                        hd = min_to_hm(start_min)
                        hf = min_to_hm(start_min + duration)
                        end_min = start_min + duration

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

                        if not is_valid_assignment(item, course_obj, d, hd, hf, r, [],
                                                lunch_debut_min, lunch_fin_min,
                                                group_day_index, occ_room, occ_teacher):
                            continue
                        soft_penalty = sum(w * fn(item, course_obj, d, hd, hf, r,
                                                group_day_index, occ_teacher, lunch_debut_min, lunch_fin_min)
                                        for fn, w in scorers)
                        candidates.append((soft_penalty, r, hd, hf, d))
            if not candidates:
                not_done.append(item)
                # ----------- Diagnnostic ----------- #
                diag_day  = locked_info["days"] if locked_info["days"] is not None else (locked_info["weeks"][0] if locked_info["weeks"] else None)
                diag_hd   = locked_info["hd"]
                diag_room = locked_info["room"]

                if days_range == []:
                    print(f"  ✗ Impossible de placer '{item.course}' : la date demandée est déjà passée")

                if diag_day is not None and diag_hd is not None:
                    diag_hf = min_to_hm(hm(diag_hd) + duration)
                    slot_reason = _conflict_reason(item, diag_day, diag_hd, diag_hf, group_day_index, occ_teacher)
                    if slot_reason != "ok":
                        print(f"  ✗ Impossible de placer '{item.course}' : {slot_reason}")
                    elif diag_room is not None:
                        room_reason = _room_reject_reason(item, diag_room.name, course_obj, room_map)
                        print(f"  ✗ Impossible de placer '{item.course}' : salle {diag_room.name} indisponible ({room_reason})")
                    else:
                        print(f"  ✗ Impossible de placer '{item.course}' à {fmt_abs_day(diag_day)} {diag_hd} : aucune salle disponible.")
                else:
                    print(f"  ✗ Impossible de placer '{item.course}' sur tout le semestre.")
            else:
                candidates.sort(key=lambda c: c[0])
                new_item = item._replace(room=candidates[0][1].name, building=candidates[0][1].bat, heure_debut=candidates[0][2], heure_fin=candidates[0][3], day=candidates[0][4])
                new_schedule.append(new_item)
                done.append(new_item)
    else:
        new_schedule = schedule_solver
        done.extend(placed_items)
        not_done = cancelled_items

    return new_schedule, done, not_done, status

# ===========================================================================
# SCÉNARIO ENLEVER UNE SESSION
# ===========================================================================
def remove_sessions(
        schedule: List[ScheduleItem],
        to_remove: List[ScheduleItem],
    ) -> Tuple[List[ScheduleItem], List[ScheduleItem], List[ScheduleItem], str]:
    """
    [!] A COMPLETER
    """
    new_schedule = list(schedule)

    to_remove_fr = [it for it in to_remove if it.day >= basics.MIN_DAY]

    ok = []
    not_ok = []

    for item in to_remove_fr:
        if item.day < basics.MIN_DAY:
            print(f"  ✗ '{item.course}' [{', '.join(g.id for g in item.group)}] {fmt_abs_day(item.day)} : session déjà passée, ignorée")
        try:
            new_schedule.remove(item)
            ok.append(item)
        except:
            not_ok.append(item)

    status = "OPTIMAL" if len(ok)==len(to_remove_fr) else "PARTIAL"
    return new_schedule, ok, not_ok, status

