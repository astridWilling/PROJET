from basics import *
import bisect


def _expand_groups(groups: List["Group"]) -> List[str]:
    """Pour chaque Group, remonte la hiérarchie via group.ancestors().
    Retourne la liste dédupliquée des IDs à indexer (self + tous les ancêtres)."""
    result = []
    for g in groups:
        result.extend(g.ancestors())
    return result


def build_occupations(schedule: List[ScheduleItem]):
    """
    Construit les structures d'occupation minute par minute.

    Retourne (group_day_index, occ_room, occ_teacher) :
      - group_day_index : dict {(group, day): sorted list of minutes}
        Utilisé pour les checks de conflit groupe (bisect O(log n))
        ET pour les scorers (accès direct par clé, pas de scan du set entier).
      - occ_room    : set {(room_name, day, minute)} — conflict check O(1)
      - occ_teacher : set {(teacher_id, day, minute)} — conflict check O(1)
    """
    group_day_index: dict = defaultdict(list)
    occ_room:    OccRoom    = set()
    occ_teacher: OccTeacher = set()

    for item in schedule:
        t1, t2 = hm(item.heure_debut), hm(item.heure_fin)
        minutes = list(range(t1, t2))
        for gid in _expand_groups(item.group):
            group_day_index[(gid, item.day)].extend(minutes)
        for m in minutes:
            occ_room.add((item.room,          item.day, m))
            occ_teacher.add((item.teacher.id, item.day, m))

    # Trier une seule fois après construction (plus rapide que bisect.insort à la volée)
    for key in group_day_index:
        group_day_index[key].sort()

    return group_day_index, occ_room, occ_teacher


def _group_conflict(group: str, day: int, t1: int, t2: int,
                    group_day_index: dict) -> bool:
    """Vérifie si [t1, t2) chevauche l'occupation connue du groupe ce jour."""
    minutes = group_day_index.get((group, day))
    if not minutes:
        return False
    lo = bisect.bisect_left(minutes, t1)
    hi = bisect.bisect_left(minutes, t2)
    return lo < hi  # au moins une minute occupée dans [t1, t2)


def _do_place(item: ScheduleItem, day: int, heure_debut: str, heure_fin: str, room: Room,
              new_schedule: List[ScheduleItem],
              group_day_index: dict, occ_room: OccRoom, occ_teacher: OccTeacher) -> None:
    new_item = item._replace(day=day, heure_debut=heure_debut, heure_fin=heure_fin,
                             room=room.name, building=room.bat)
    new_schedule.append(new_item)
    t1, t2 = hm(heure_debut), hm(heure_fin)
    for gid in _expand_groups(item.group):
        lst = group_day_index[(gid, day)]
        for m in range(t1, t2):
            bisect.insort(lst, m)
    for m in range(t1, t2):
        occ_room.add((room.name,          day, m))
        occ_teacher.add((item.teacher.id, day, m))


def is_valid_assignment(
    item:             ScheduleItem,
    course:           Course,
    day:              int,
    heure_debut:      str,
    heure_fin:        str,
    room:             Room,
    absent_intervals: AbsentIntervals,
    lunch_debut_min:  int,
    lunch_fin_min:    int,
    group_day_index:  dict,
    occ_room:         OccRoom,
    occ_teacher:      OccTeacher,
    ) -> bool:
    """
    Vérifie si l'item peut être placé à (day, heure_debut, heure_fin) dans room.
    """
    total_hc = sum(g.headcount for g in item.group)
    if room.capacity < total_hc:                                      return False
    # session_type (CSV) donne le type de CETTE séance ; course.room_types liste TOUS les types du cours.
    # Si session_type est générique (ex: "TP") et course.room_types contient un sous-type plus précis
    # (ex: "TP_SI"), on utilise le sous-type. Sinon on garde session_type tel quel.
    if item.session_type:
        specific = [rt for rt in course.room_types if rt.startswith(item.session_type) and rt != item.session_type]
        req = specific if specific else [item.session_type]
    else:
        req = course.room_types
    if req and not any(rt in room.room_types for rt in req):          return False

    t1, t2 = hm(heure_debut), hm(heure_fin)
    if t1 >= t2:                                                      return False

    for (ad, ah_debut, ah_fin) in absent_intervals:
        if ad == day:
            ah1, ah2 = hm(ah_debut), hm(ah_fin)
            if t1 < ah2 and ah1 < t2:
                return False

    for gid in _expand_groups(item.group):
        if _group_conflict(gid, day, t1, t2, group_day_index):        return False
    for m in range(t1, t2):
        if (room.name,        day, m) in occ_room:    return False
        if (item.teacher.id,  day, m) in occ_teacher: return False

    lunch_overlap = max(0, min(t2, lunch_fin_min) - max(t1, lunch_debut_min))
    if lunch_overlap > 0:
        for g in item.group:
            gd_mins     = group_day_index.get((g.id, day), [])
            lo_l        = bisect.bisect_left(gd_mins, lunch_debut_min)
            hi_l        = bisect.bisect_left(gd_mins, lunch_fin_min)
            group_free  = (lunch_fin_min - lunch_debut_min) - (hi_l - lo_l)
            if group_free - lunch_overlap < LUNCH_MIN_FREE_MINUTES: return False
        teach_free = sum(1 for m in range(lunch_debut_min, lunch_fin_min)
                         if (item.teacher.id, day, m) not in occ_teacher)
        if teach_free - lunch_overlap < LUNCH_MIN_FREE_MINUTES: return False

    return True


def try_place(
    item:             ScheduleItem,
    course:           Course,
    nb_days:          int,
    rooms:            List[Room],
    valid_starts:     List[int],
    absent_intervals: AbsentIntervals,
    lunch_debut_min:  int,
    lunch_fin_min:    int,
    group_day_index:  dict,
    occ_room:         OccRoom,
    occ_teacher:      OccTeacher,
    new_schedule:     List[ScheduleItem],
    soft_scorers:     Optional[ScorerList] = None,
    min_day:          int = 0,
    locked_slot:      "Optional[Tuple[int, str]]" = None,
) -> bool:
    """
    Greedy : cherche le meilleur placement valide parmi tous les candidats, et place l'item.
    locked_slot = (day, heure_debut) pour forcer jour ET créneau (ex: room_unavailable).
    """
    scorers  = soft_scorers or []
    dur_min  = hm(item.heure_fin) - hm(item.heure_debut)
    candidates = []

    for day in range(min_day, nb_days):
        if locked_slot is not None and day != locked_slot[0]:
            continue
        for start_min in valid_starts:
            heure_debut = min_to_hm(start_min)
            if locked_slot is not None and heure_debut != locked_slot[1]:
                continue
            heure_fin   = min_to_hm(start_min + dur_min)
            for room in rooms:
                if not is_valid_assignment(
                    item, course, day, heure_debut, heure_fin, room,
                    absent_intervals, lunch_debut_min, lunch_fin_min,
                    group_day_index, occ_room, occ_teacher,
                ):
                    continue
                soft_penalty = sum(
                    w * fn(item, course, day, heure_debut, heure_fin, room,
                           group_day_index, occ_teacher, lunch_debut_min, lunch_fin_min)
                    for fn, w in scorers
                )
                room_fit = (room.capacity - sum(g.headcount for g in item.group)) / max(room.capacity, 1)
                candidates.append((soft_penalty, room_fit, day, start_min,
                                   heure_debut, heure_fin, room))

    if not candidates:
        return False

    candidates.sort(key=lambda c: (c[0], c[1], c[2], c[3]))
    _, _, best_day, _, best_hdebut, best_hfin, best_room = candidates[0]
    _do_place(item, best_day, best_hdebut, best_hfin, best_room,
              new_schedule, group_day_index, occ_room, occ_teacher)
    return True


def greedy_fallback(
    to_reschedule:    List[ScheduleItem],
    fixed_schedule:   List[ScheduleItem],
    courses:          List[Course],
    rooms:            List[Room],
    nb_days:          int,
    valid_starts:     List[int],
    absent_intervals: AbsentIntervals,
    lunch_debut_min:  int,
    lunch_fin_min:    int,
    soft_scorers:     Optional[ScorerList] = None,
    min_day:          int = 0,
    locked_slots:     Optional[dict] = None,
) -> Tuple[List[ScheduleItem], List[ScheduleItem], List[ScheduleItem]]:
    """
    Greedy cours par cours.  Retourne (new_schedule, cancelled, rescheduled).
    rescheduled = items effectivement placés (avec leur nouvelle position).
    locked_slots = {id(item): (day, heure_debut)} pour forcer jour ET créneau.
    """
    course_map = {c.id: c for c in courses}
    course_map.update({str(c.id): c for c in courses})

    n_fixed      = len(fixed_schedule)
    new_schedule = list(fixed_schedule)
    group_day_index, occ_room, occ_teacher = build_occupations(new_schedule)
    cancelled: List[ScheduleItem] = []

    for item in to_reschedule:
        placed = try_place(
            item=item,
            course=course_map[base_course_id(item.course)],
            nb_days=nb_days,
            rooms=rooms,
            valid_starts=valid_starts,
            absent_intervals=absent_intervals,
            lunch_debut_min=lunch_debut_min,
            lunch_fin_min=lunch_fin_min,
            group_day_index=group_day_index,
            occ_room=occ_room,
            occ_teacher=occ_teacher,
            new_schedule=new_schedule,
            soft_scorers=soft_scorers,
            min_day=min_day,
            locked_slot=(locked_slots or {}).get(id(item)),
        )
        if not placed:
            cancelled.append(item)

    return new_schedule, cancelled, new_schedule[n_fixed:]


#!############################################################
#! Partie pour la résolution des perturbations en une passe
#!############################################################
def is_valid_assignment_with_blocked(
    item:             ScheduleItem,
    course:           Course,
    day:              int,
    heure_debut:      str,
    heure_fin:        str,
    room:             Room,
    absent_intervals: AbsentIntervals,
    lunch_debut_min:  int,
    lunch_fin_min:    int,
    group_day_index:  dict,
    occ_room:         OccRoom,
    occ_teacher:      OccTeacher,
    teacher_blocked:  dict,  # teacher_id -> [(day, h_debut, h_fin), ...]
    groups_blocked:   dict,  # group_id   -> [(day, h_debut, h_fin), ...]
    rooms_blocked:    dict,  # room_name  -> [(day, h_debut, h_fin), ...]
) -> bool:
    if not is_valid_assignment(
        item, course, day, heure_debut, heure_fin, room,
        absent_intervals, lunch_debut_min, lunch_fin_min,
        group_day_index, occ_room, occ_teacher,
    ):
        return False

    t1, t2 = hm(heure_debut), hm(heure_fin)

    # Vérifier les créneaux bloqués pour le prof
    for (bd, bh_debut, bh_fin) in teacher_blocked.get(item.teacher.id, []):
        if bd == day and t1 < hm(bh_fin) and hm(bh_debut) < t2:
            return False

    # Vérifier les créneaux bloqués pour les groupes
    for g in item.group:
        for (bd, bh_debut, bh_fin) in groups_blocked.get(g.id, []):
            if bd == day and t1 < hm(bh_fin) and hm(bh_debut) < t2:
                return False

    # Vérifier les créneaux bloqués pour la salle
    room_intervals = rooms_blocked.get(room.name, [])
    if room_intervals is None:   # Si on a bloqué la salle pour tout le semestre
        return False
    for (bd, bh_debut, bh_fin) in room_intervals:
        if bd == day and t1 < hm(bh_fin) and hm(bh_debut) < t2:
            return False

    return True

#! Rajouter locked_slot a is_valid_assignment pour pouvoir ajouter le if lunch_overlap > 0 and not locked_slot au lieu de juste if lunch_overlap > 0
            #! => permet de ne pas bloquer le changement de salle quand on lance une perturbation salle indispo avec perturb.py quand la session est dans un lunch_slot
def try_place_with_blocked(
    item:             ScheduleItem,
    course:           Course,
    nb_days:          int,
    rooms:            List[Room],
    valid_starts:     List[int],
    absent_intervals: AbsentIntervals,
    teacher_blocked:  dict,  # teacher_id -> [(day, h_debut, h_fin), ...]
    groups_blocked:   dict,  # group_id   -> [(day, h_debut, h_fin), ...]
    rooms_blocked:    dict,  # room_name  -> [(day, h_debut, h_fin), ...]
    lunch_debut_min:  int,
    lunch_fin_min:    int,
    group_day_index:  dict,
    occ_room:         OccRoom,
    occ_teacher:      OccTeacher,
    new_schedule:     List[ScheduleItem],
    soft_scorers:     Optional[ScorerList] = None,
    min_day:          int = 0,
    locked_slot:      "Optional[Tuple[int, str]]" = None,
) -> bool:
    """
    Greedy : cherche le meilleur placement valide parmi tous les candidats.
    locked_slot = (day, heure_debut) pour forcer jour ET créneau (ex: room_unavailable).
    """
    scorers  = soft_scorers or []
    dur_min  = hm(item.heure_fin) - hm(item.heure_debut)
    candidates = []

    nb_blocked_teacher = 0
    nb_blocked_group = 0
    nb_blocked_room = 0


    for day in range(min_day, nb_days):
        if locked_slot is not None and day != locked_slot[0]:
            continue
        for start_min in valid_starts:
            heure_debut = min_to_hm(start_min)
            if locked_slot is not None and heure_debut != locked_slot[1]:
                continue
            heure_fin   = min_to_hm(start_min + dur_min)
            end_min = start_min + dur_min
            for room in rooms:

                blocked = False
                for (abd, abh, abf) in (teacher_blocked or {}).get(item.teacher.id, []):
                    if abd == day and start_min < hm(abf) and hm(abh) < end_min:
                        blocked = True; nb_blocked_teacher += 1; break
                if not blocked:
                    for g in item.group:
                        for (abd, abh, abf) in (groups_blocked or {}).get(g.id, []):
                            if abd == day and start_min < hm(abf) and hm(abh) < end_min:
                                blocked = True; nb_blocked_group += 1; break
                        if blocked: break
                if not blocked:
                    for (abd, abh, abf) in (rooms_blocked or {}).get(room.name, []):
                        if abd == day and start_min < hm(abf) and hm(abh) < end_min:
                            blocked = True; nb_blocked_room += 1; break
                if blocked:
                    continue

                if not is_valid_assignment(
                    item, course, day, heure_debut, heure_fin, room,
                    absent_intervals, lunch_debut_min, lunch_fin_min,
                    group_day_index, occ_room, occ_teacher
                ):
                    continue
                soft_penalty = sum(
                    w * fn(item, course, day, heure_debut, heure_fin, room,
                           group_day_index, occ_teacher, lunch_debut_min, lunch_fin_min)
                    for fn, w in scorers
                )
                room_fit = (room.capacity - sum(g.headcount for g in item.group)) / max(room.capacity, 1)
                candidates.append((soft_penalty, room_fit, day, start_min,
                                   heure_debut, heure_fin, room))

    if not candidates:
        reason = []
        if nb_blocked_teacher > 0 : reason.append(f"Aucun créneau avec un professeur disponible")
        if nb_blocked_group > 0 : reason.append(f"Aucun créneau où le groupe est disponible")
        if nb_blocked_room > 0 : reason.append(f"Aucun créneau avec une salle disponible")
        print(f"  [!] Aucun placement valide pour {item.course} {', '.join([g.id for g in item.group])} ({fmt_abs_day(item.day)}, {item.heure_debut}-{item.heure_fin} — {', '.join(reason) if reason else 'contraintes planning'}")

        return False

    candidates.sort(key=lambda c: (c[0], c[1], c[2], c[3]))
    _, _, best_day, _, best_hdebut, best_hfin, best_room = candidates[0]
    _do_place(item, best_day, best_hdebut, best_hfin, best_room,
              new_schedule, group_day_index, occ_room, occ_teacher)
    return True

def greedy_fallback_with_blocked(
    to_reschedule:    List[ScheduleItem],
    fixed_schedule:   List[ScheduleItem],
    courses:          List[Course],
    rooms:            List[Room],
    nb_days:          int,
    valid_starts:     List[int],
    absent_intervals: AbsentIntervals,
    lunch_debut_min:  int,
    lunch_fin_min:    int,
    teacher_blocked:  dict,  # teacher_id -> [(day, h_debut, h_fin), ...]
    groups_blocked:   dict,  # group_id   -> [(day, h_debut, h_fin), ...]
    rooms_blocked:    dict,  # room_name  -> [(day, h_debut, h_fin), ...]
    soft_scorers:     Optional[ScorerList] = None,
    min_day:          int = 0,
    locked_slots:     Optional[dict] = None,
) -> Tuple[List[ScheduleItem], List[ScheduleItem], List[ScheduleItem]]:
    """
    Greedy cours par cours.  Retourne (new_schedule, cancelled, rescheduled).
    rescheduled = items effectivement placés (avec leur nouvelle position).
    """
    course_map = {c.id: c for c in courses}
    course_map.update({str(c.id): c for c in courses})

    n_fixed      = len(fixed_schedule)
    new_schedule = list(fixed_schedule)
    group_day_index, occ_room, occ_teacher = build_occupations(new_schedule)
    cancelled: List[ScheduleItem] = []

    for item in to_reschedule:
        placed = try_place_with_blocked(
            item=item,
            course=course_map[base_course_id(item.course)],
            nb_days=nb_days,
            rooms=rooms,
            valid_starts=valid_starts,
            absent_intervals=absent_intervals,
            teacher_blocked=teacher_blocked,
            groups_blocked=groups_blocked,
            rooms_blocked=rooms_blocked,
            lunch_debut_min=lunch_debut_min,
            lunch_fin_min=lunch_fin_min,
            group_day_index=group_day_index,
            occ_room=occ_room,
            occ_teacher=occ_teacher,
            new_schedule=new_schedule,
            soft_scorers=soft_scorers,
            min_day=min_day,
            locked_slot=(locked_slots or {}).get(id(item)),
        )
        if not placed:
            cancelled.append(item)

    return new_schedule, cancelled, new_schedule[n_fixed:]