from typing import List, Tuple, Set, Optional, Callable
from basics import Course, Room, ScheduleItem

# ---------------------------------------------------------------------------
# Alias de types
# ---------------------------------------------------------------------------
TimeKey     = Tuple[int, int]
AbsentSlots = Set[TimeKey]
OccGroup    = Set[Tuple[str, TimeKey]]
OccRoom     = Set[Tuple[str, TimeKey]]
OccTeacher  = Set[Tuple[str, TimeKey]]

# Type d'une fonction de score :
# (item, course, day, slot, room, occ_group, occ_teacher, lunch_slots, nb_slots_per_day) -> float
Scorer = Callable[..., float]
ScorerList = List[Tuple[Scorer, float]]   # [(fn, weight), ...]


# ===========================================================================
# FONCTIONS DE SCORE LOCALES
# Chaque scorer évalue l'impact d'UN placement (day, slot, room) sur une
# contrainte souple. Il retourne une pénalité (≥ 0 = mauvais, < 0 = bon).
# Ces scores sont des APPROXIMATIONS LOCALES des contraintes CP-SAT :
# ils capturent l'essentiel sans résoudre un modèle entier.
# ===========================================================================

def score_no_late_day(item, course, day, slot, room,
                      occ_group, occ_teacher, lunch_slots, nb_slots_per_day) -> float:
    """Pénalité si le slot est dans les 2 derniers créneaux du jour (trop tardif)."""
    return 1.0 if slot >= nb_slots_per_day - 2 else 0.0


def score_no_late_day_teacher(item, course, day, slot, room,
                               occ_group, occ_teacher, lunch_slots, nb_slots_per_day) -> float:
    """Même pénalité pour le prof (créneau tardif = mauvais pour tout le monde)."""
    return 1.0 if slot >= nb_slots_per_day - 2 else 0.0


def score_long_lunch(item, course, day, slot, room,
                     occ_group, occ_teacher, lunch_slots, nb_slots_per_day) -> float:
    """
    Pénalité si placement dans un lunch slot pour le GROUPE.
    Plus il y a de lunch slots déjà occupés, plus la pénalité est élevée :
    on veut préserver un maximum de slots libres au déjeuner.
    Retourne 0 si le slot n'est pas un slot déjeuner.
    """
    if slot not in lunch_slots:
        return 0.0
    already = sum(1 for ls in lunch_slots if (item.group, (day, ls)) in occ_group)
    return float(already + 1)   # de 1.0 (1er slot lunch) à len(lunch_slots) (tous pris)


def score_long_lunch_teacher(item, course, day, slot, room,
                              occ_group, occ_teacher, lunch_slots, nb_slots_per_day) -> float:
    """Même pénalité pour le PROF."""
    if slot not in lunch_slots:
        return 0.0
    already = sum(1 for ls in lunch_slots if (item.teacher.id, (day, ls)) in occ_teacher)
    return float(already + 1)


def score_no_gap(item, course, day, slot, room,
                 occ_group, occ_teacher, lunch_slots, nb_slots_per_day) -> float:
    """
    Impact du placement sur les trous (gaps) dans le planning du GROUPE.
    Valeur positive : crée de nouveaux gaps (mauvais).
    Valeur négative : comble un gap existant (bon → ce placement est préféré).
    Les slots déjeuner sont exclus du calcul des gaps.
    """
    if slot in lunch_slots:
        return 0.0

    delta = 0.0
    g = item.group

    def occ(s: int) -> bool:
        return (0 <= s < nb_slots_per_day
                and s not in lunch_slots
                and (g, (day, s)) in occ_group)

    # Placer à `slot` crée un gap à slot-1 si slot-2 est occupé et slot-1 est libre
    if occ(slot - 2) and not occ(slot - 1):
        delta += 1.0
    # Placer à `slot` crée un gap à slot+1 si slot+1 est libre et slot+2 est occupé
    if not occ(slot + 1) and occ(slot + 2):
        delta += 1.0
    # Placer à `slot` comble un gap existant si slot-1 et slot+1 sont occupés
    if occ(slot - 1) and occ(slot + 1):
        delta -= 1.0   # gap comblé = bonne chose → score négatif

    return delta


def score_no_gap_teacher(item, course, day, slot, room,
                          occ_group, occ_teacher, lunch_slots, nb_slots_per_day) -> float:
    """Même logique pour le PROF."""
    if slot in lunch_slots:
        return 0.0

    delta = 0.0
    tid = item.teacher.id

    def occ_t(s: int) -> bool:
        return (0 <= s < nb_slots_per_day
                and s not in lunch_slots
                and (tid, (day, s)) in occ_teacher)

    if occ_t(slot - 2) and not occ_t(slot - 1):
        delta += 1.0
    if not occ_t(slot + 1) and occ_t(slot + 2):
        delta += 1.0
    if occ_t(slot - 1) and occ_t(slot + 1):
        delta -= 1.0

    return delta


# ---------------------------------------------------------------------------
# Scorer de salle — toujours appliqué, indépendamment du log
# ---------------------------------------------------------------------------

def score_room_fit(item, course, day, slot, room,
                   occ_group, occ_teacher, lunch_slots, nb_slots_per_day) -> float:
    """
    Préfère la salle dont la capacité est la plus proche du nombre d'étudiants.
    Évite de mettre 15 étudiants dans un amphi de 300 places.
    Normalisé en [0, 1] pour ne pas écraser les scores des contraintes souples.
    """
    waste = room.capacity - course.headcount          # ≥ 0 (garanti par is_valid_assignment)
    return waste / max(room.capacity, 1)              # proportion de places vides


# ---------------------------------------------------------------------------
# Mapping nom_contrainte → scorer
# ---------------------------------------------------------------------------

SOFT_SCORERS: dict = {
    "NoGap":             score_no_gap,
    "NoGapTeacher":      score_no_gap_teacher,
    "NoLateDay":         score_no_late_day,
    "NoLateDayTeacher":  score_no_late_day_teacher,
    "LongLunch":         score_long_lunch,
    "LongLunchTeacher":  score_long_lunch_teacher,
}


def build_soft_scorers(log_constraints: list) -> ScorerList:
    """
    Construit la liste (fn, weight) à partir des contraintes issues du log.

    Seules les contraintes SOUPLES (is_hard=False) reconnues dans SOFT_SCORERS
    sont incluses. Le scorer de salle (score_room_fit) est toujours ajouté
    avec un poids normalisé pour servir de critère de départage.

    Paramètre
    ---------
    log_constraints : [{"name": ..., "weight": ..., "is_hard": ...}, ...]
                      tel que retourné par load_constraints_from_log()

    Retourne
    --------
    ScorerList : [(fn, weight), ...] prête à être passée à try_place()
    """
    scorers: ScorerList = []

    for c in log_constraints:
        if c.get("is_hard", False):
            continue                         # contraintes dures déjà gérées en hard
        fn = SOFT_SCORERS.get(c["name"])
        if fn is None:
            continue                         # contrainte inconnue → ignorée
        scorers.append((fn, float(c["weight"])))

    # Scorer de salle toujours actif, avec poids = 1.0 (normalisé en [0,1])
    scorers.append((score_room_fit, 1.0))

    if scorers:
        names = [c["name"] for c in log_constraints if not c.get("is_hard") and c["name"] in SOFT_SCORERS]
        print(f"[scenario] Scorers actifs : {names} + room_fit")
    else:
        print("[scenario] Aucun scorer soft trouvé dans le log — placement greedy pur.")

    return scorers


# ===========================================================================
# FONCTIONS UTILITAIRES INTERNES
# ===========================================================================

def build_occupations(schedule: List[ScheduleItem]) -> Tuple[OccGroup, OccRoom, OccTeacher]:
    """
    Construit les ensembles d'occupation (groupe, salle, prof) pour des lookups O(1).
    """
    occ_group   = {(item.group,      (item.day, item.slot)) for item in schedule}
    occ_room    = {(item.room,       (item.day, item.slot)) for item in schedule}
    occ_teacher = {(item.teacher.id, (item.day, item.slot)) for item in schedule}
    return occ_group, occ_room, occ_teacher


def _do_place(item: ScheduleItem, day: int, slot: int, room: Room,
              new_schedule: List[ScheduleItem],
              occ_group: OccGroup, occ_room: OccRoom, occ_teacher: OccTeacher) -> None:
    """Place item au créneau (day, slot, room) et met à jour toutes les occupations."""
    new_item = item._replace(day=day, slot=slot, room=room.name)
    new_schedule.append(new_item)
    time_key: TimeKey = (day, slot)
    occ_group.add((item.group,       time_key))
    occ_room.add((room.name,         time_key))
    occ_teacher.add((item.teacher.id, time_key))


def is_valid_assignment(
    item:         ScheduleItem,
    course:       Course,
    day:          int,
    slot:         int,
    room:         Room,
    absent_slots: AbsentSlots,
    lunch_slots:  List[int],
    occ_group:    OccGroup,
    occ_room:     OccRoom,
    occ_teacher:  OccTeacher,
) -> bool:
    """
    Vérifie que (day, slot, room) est un placement RÉALISABLE (hard constraints) :
      - pas un créneau d'absence
      - pas de conflit groupe / salle / prof
      - salle compatible (capacité + type)
      - groupe ET prof conservent au moins 1 lunch slot libre ce jour-là
    Les contraintes souples sont évaluées séparément dans les scorers.
    """
    if (day, slot) in absent_slots:
        return False

    time_key: TimeKey = (day, slot)

    if (item.group,       time_key) in occ_group:   return False
    if (room.name,        time_key) in occ_room:    return False
    if (item.teacher.id,  time_key) in occ_teacher: return False
    if room.capacity < course.headcount:             return False
    if not any(rt in course.room_types for rt in room.room_types): return False

    # Contrainte déjeuner dure : groupe ET prof gardent ≥ 1 slot libre
    if slot in lunch_slots:
        group_occ = sum(1 for ls in lunch_slots if (item.group,      (day, ls)) in occ_group)
        teach_occ = sum(1 for ls in lunch_slots if (item.teacher.id, (day, ls)) in occ_teacher)
        if group_occ >= len(lunch_slots) - 1: return False
        if teach_occ >= len(lunch_slots) - 1: return False

    return True


def try_place(
    item:             ScheduleItem,
    course:           Course,
    nb_days:          int,
    nb_slots_per_day: int,
    rooms:            List[Room],
    absent_slots:     AbsentSlots,
    lunch_slots:      List[int],
    occ_group:        OccGroup,
    occ_room:         OccRoom,
    occ_teacher:      OccTeacher,
    new_schedule:     List[ScheduleItem],
    soft_scorers:     Optional[ScorerList] = None,
) -> bool:
    """
    Tente de placer `item` dans le meilleur créneau valide.

    Stratégie
    ---------
    Pour chaque (day, slot, room) réalisable (hard constraints), on calcule :
      penalty = Σ weight_i * scorer_i(day, slot, room)   ← contraintes souples
      room_fit = (capacity - headcount) / capacity        ← toujours appliqué

    On choisit le candidat minimisant (penalty, room_fit, day, slot) — soit le
    placement le plus respectueux des contraintes souples, dans la salle la mieux
    adaptée, le plus tôt possible en cas d'égalité.

    Si soft_scorers est None ou vide, on prend simplement le premier valide
    dans la salle la mieux adaptée (le plus tôt = day 0, slot 0).

    Retourne True si placé, False si aucun créneau valide trouvé.
    """
    scorers = soft_scorers or []
    candidates = []

    for day in range(nb_days):
        for slot in range(nb_slots_per_day):
            for room in rooms:
                if not is_valid_assignment(
                    item, course, day, slot, room,
                    absent_slots, lunch_slots, occ_group, occ_room, occ_teacher,
                ):
                    continue

                # Score soft (0 si pas de scorers)
                soft_penalty = sum(
                    w * fn(item, course, day, slot, room,
                           occ_group, occ_teacher, lunch_slots, nb_slots_per_day)
                    for fn, w in scorers
                )

                # Score salle : proportion de places vides (toujours actif)
                room_fit = (room.capacity - course.headcount) / max(room.capacity, 1)

                # Clé de tri : (penalité soft, gaspillage salle, jour, slot)
                # La salle n'est pas dans la clé pour éviter les comparaisons de NamedTuples
                candidates.append((soft_penalty, room_fit, day, slot, room))

    if not candidates:
        return False

    # Meilleur candidat : min sur (soft_penalty, room_fit, day, slot)
    candidates.sort(key=lambda c: (c[0], c[1], c[2], c[3]))
    _, _, best_day, best_slot, best_room = candidates[0]

    _do_place(item, best_day, best_slot, best_room,
              new_schedule, occ_group, occ_room, occ_teacher)
    return True


# ===========================================================================
# SCÉNARIOS
# ===========================================================================

import re as _re

def _base_course_id(cid):
    """Strip le suffixe '_w{n}_s{n}' ajouté en mode semestre."""
    m = _re.match(r'^(.+)_w\d+_s\d+$', str(cid))
    return m.group(1) if m else cid


def teacher_absent(
    schedule:         List[ScheduleItem],
    courses:          List[Course],
    rooms:            List[Room],
    nb_days:          int,
    nb_slots_per_day: int,
    teacher_id:       str,
    absent_slots:     List[TimeKey],
    lunch_slots:      List[int],
    soft_scorers:     Optional[ScorerList] = None,
) -> Tuple[List[ScheduleItem], List[ScheduleItem]]:
    """
    Replanifie les cours d'un prof absent.

    Paramètres
    ----------
    teacher_id   : ID du prof (ex: "T1"), visible dans le HTML sous "Prof_1 (T1)"
    absent_slots : [(day, slot), ...] créneaux d'absence
    lunch_slots  : indices des créneaux déjeuner
    soft_scorers : scorers construits par build_soft_scorers() depuis le log.
                   Si None, placement greedy pur (premier créneau valide).

    Retourne
    --------
    (new_schedule, cancelled)
    """
    course_map = {}
    for c in courses:
        course_map[c.id] = c
        course_map[str(c.id)] = c
    absent_set: AbsentSlots = set(absent_slots)

    to_reschedule: List[ScheduleItem] = []
    new_schedule:  List[ScheduleItem] = []

    for item in schedule:
        if item.teacher.id == teacher_id and (item.day, item.slot) in absent_set:
            to_reschedule.append(item)
        else:
            new_schedule.append(item)

    print(f"{len(to_reschedule)} session(s) à replanifier pour {teacher_id}.")

    occ_group, occ_room, occ_teacher = build_occupations(new_schedule)
    cancelled: List[ScheduleItem] = []

    for item in to_reschedule:
        placed = try_place(
            item=item,
            course=course_map[_base_course_id(item.course)],
            nb_days=nb_days,
            nb_slots_per_day=nb_slots_per_day,
            rooms=rooms,
            absent_slots=absent_set,
            lunch_slots=lunch_slots,
            occ_group=occ_group,
            occ_room=occ_room,
            occ_teacher=occ_teacher,
            new_schedule=new_schedule,
            soft_scorers=soft_scorers,
        )
        if not placed:
            cancelled.append(item)

    return new_schedule, cancelled


def room_unavailable(
    schedule:         List[ScheduleItem],
    courses:          List[Course],
    rooms:            List[Room],
    nb_days:          int,
    nb_slots_per_day: int,
    room_name:        str,
    lunch_slots:      List[int],
    absent_slots:     Optional[List[TimeKey]] = None,
    soft_scorers:     Optional[ScorerList]    = None,
) -> Tuple[List[ScheduleItem], List[ScheduleItem]]:
    """
    Replanifie les sessions dont la salle est devenue indisponible.

    Paramètres
    ----------
    room_name    : nom de la salle indisponible (ex: "TD1")
    absent_slots : [(day, slot), ...] créneaux où la salle est bloquée.
                   None = salle retirée de TOUS les créneaux (durée inconnue).
    lunch_slots  : indices des créneaux déjeuner
    soft_scorers : scorers construits par build_soft_scorers() depuis le log.

    Note : la session peut rester au même (day, slot) dans une autre salle.
    Seule la salle indisponible est exclue des candidats.
    """
    course_map = {}
    for c in courses:
        course_map[c.id] = c
        course_map[str(c.id)] = c

    if absent_slots is None:
        absent_set: AbsentSlots = {
            (d, s) for d in range(nb_days) for s in range(nb_slots_per_day)
        }
    else:
        absent_set = set(absent_slots)

    to_reschedule: List[ScheduleItem] = []
    new_schedule:  List[ScheduleItem] = []

    for item in schedule:
        if item.room == room_name and (item.day, item.slot) in absent_set:
            to_reschedule.append(item)
        else:
            new_schedule.append(item)

    print(f"{len(to_reschedule)} session(s) à replanifier (salle {room_name!r} indisponible).")

    occ_group, occ_room, occ_teacher = build_occupations(new_schedule)

    # Retirer la salle indisponible sans muter la liste originale
    rooms_ok = [r for r in rooms if r.name != room_name]

    cancelled: List[ScheduleItem] = []

    for item in to_reschedule:
        placed = try_place(
            item=item,
            course=course_map[_base_course_id(item.course)],
            nb_days=nb_days,
            nb_slots_per_day=nb_slots_per_day,
            rooms=rooms_ok,
            absent_slots=frozenset(),   # pas de blocage par créneau, juste par salle
            lunch_slots=lunch_slots,
            occ_group=occ_group,
            occ_room=occ_room,
            occ_teacher=occ_teacher,
            new_schedule=new_schedule,
            soft_scorers=soft_scorers,
        )
        if not placed:
            cancelled.append(item)

    return new_schedule, cancelled
