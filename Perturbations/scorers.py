from basics import hm, min_to_hm, OccGroup, OccTeacher, LATE_COURSE_MAX, MAX_HOURS_BY_TYPE, DEADLINE_BUFFER_DAYS
from basics import ScheduleItem, Course, Room, Building, Teacher
from typing import List, Dict
from greedy import build_occupations


def compute_hours(teacher_id: str, schedule: List[ScheduleItem]) -> float:
    """Heures de cours d'un prof dans le planning donné (en heures décimales)."""
    return sum(
        (hm(item.heure_fin) - hm(item.heure_debut)) / 60.0
        for item in schedule
        if item.teacher.id == teacher_id
    )


def remaining_hours(teacher: Teacher, schedule: List[ScheduleItem]) -> float:
    """Heures restantes avant quota (inf si pas de quota défini)."""
    max_h = teacher.max_hours
    if max_h is None and teacher.teacher_type:
        max_h = MAX_HOURS_BY_TYPE.get(teacher.teacher_type)
    if max_h is None:
        return float("inf")
    return max_h - compute_hours(teacher.id, schedule)

# ---------------------------------------------------------------------------
# Helpers internes
# ---------------------------------------------------------------------------

def _group_minutes_on_day(group: str, day: int, group_day_index: dict) -> list:
    # group_day_index est un dict {(group, day): sorted list} — accès O(1) au lieu
    # du scan linéaire O(|occ_group|) de l'ancienne version basée sur un set.
    return group_day_index.get((group, day), [])


# ---------------------------------------------------------------------------
# score_no_late_group
# ---------------------------------------------------------------------------
# Pénalise si la fin du cours dépasse LATE_COURSE_MAX (défini dans basics.py).
# Pénalité proportionnelle au dépassement, en heures.
# Exemple : cours finit à 18h00, seuil = 17h00 → pénalité = 1.0
# ---------------------------------------------------------------------------
def score_no_late_group(item, course, day, hd, hf, room,
                        occ_group, occ_teacher, lunch_debut_min, lunch_fin_min):
    return max(0, hm(hf) - LATE_COURSE_MAX) / 60.0


# ---------------------------------------------------------------------------
# score_no_late_teacher
# ---------------------------------------------------------------------------
# Même logique pour le prof.
# ---------------------------------------------------------------------------
def score_no_late_teacher(item, course, day, hd, hf, room,
                          occ_group, occ_teacher, lunch_debut_min, lunch_fin_min):
    return max(0, hm(hf) - LATE_COURSE_MAX) / 60.0


# ---------------------------------------------------------------------------
# score_no_gap_group
# ---------------------------------------------------------------------------
# Pénalise les trous dans la journée du groupe (hors pause midi).
# Logique :
#   1. Récupère les minutes déjà occupées par le groupe ce jour-là.
#   2. Ajoute les minutes du nouveau cours.
#   3. Scanne de la première à la dernière minute occupée.
#   4. Chaque plage libre > GAP_THRESHOLD minutes (hors midi) contribue
#      à la pénalité (minutes en excès / 60).
# GAP_THRESHOLD = 15 min de tolérance pour les transitions entre salles.
# ---------------------------------------------------------------------------
GAP_THRESHOLD = 15

def score_no_gap_group(item, course, day, hd, hf, room,
                       occ_group, occ_teacher, lunch_debut_min, lunch_fin_min):
    t1, t2 = hm(hd), hm(hf)
    total_penalty = 0.0
    for g in item.group:
        occupied = set(_group_minutes_on_day(g.id, day, occ_group))
        if not occupied:
            continue  # premier cours du groupe ce jour-là, pas de trou possible
        occupied |= set(range(t1, t2))
        day_start = min(occupied)
        day_end   = max(occupied)
        gap_total        = 0
        consecutive_free = 0
        for m in range(day_start, day_end + 1):
            in_lunch = lunch_debut_min <= m < lunch_fin_min
            if m not in occupied and not in_lunch:
                consecutive_free += 1
            else:
                if consecutive_free > GAP_THRESHOLD:
                    gap_total += consecutive_free - GAP_THRESHOLD
                consecutive_free = 0
        total_penalty += gap_total / 60.0
    return total_penalty


# ---------------------------------------------------------------------------
# score_same_day
# ---------------------------------------------------------------------------
# Spécifique à la perturbation : préférer placer le cours le même jour
# qu'à l'origine pour minimiser la perturbation ressentie.
# ---------------------------------------------------------------------------
def score_same_day(item, course, day, hd, hf, room,
                   occ_group, occ_teacher, lunch_debut_min, lunch_fin_min):
    # Pénalité proportionnelle au nombre de jours d'écart (0 = même jour, 1 = ±1 jour...)
    return float(abs(day - item.day))


# ---------------------------------------------------------------------------
# score_preferred_building
# ---------------------------------------------------------------------------
# Pénalité 1.0 si le bâtiment de la salle n'est pas dans course.preferred_buildings.
# Si preferred_buildings est vide, aucune pénalité (pas de préférence définie).
# ---------------------------------------------------------------------------
def score_preferred_building(item, course, day, hd, hf, room,
                             occ_group, occ_teacher, lunch_debut_min, lunch_fin_min):
    if not course.preferred_buildings:
        return 0.0
    return 0.0 if room.bat in course.preferred_buildings else 1.0


# ---------------------------------------------------------------------------
# make_score_deadline  (factory)
# ---------------------------------------------------------------------------
# Pénalise très fortement si le cours est placé après deadline - buffer_days.
# deadline_days : dict {course_id (int): jour_limite (int, 0=lundi)}
# buffer_days   : jours min à laisser avant l'exam (défaut = DEADLINE_BUFFER_DAYS)
# Retourne un scorer compatible avec la signature standard.
# ---------------------------------------------------------------------------
def make_score_deadline(deadline_days: dict, buffer_days: int = DEADLINE_BUFFER_DAYS):
    from basics import base_course_id

    def scorer(item, course, day, hd, hf, room,
               occ_group, occ_teacher, lunch_debut_min, lunch_fin_min):
        dl = deadline_days.get(base_course_id(course.id))
        if dl is None:
            return 0.0
        # Pénalité si on dépasse la limite (dernier jour autorisé = dl - buffer_days)
        return 10000.0 if day > dl - buffer_days else 0.0

    return scorer


# ---------------------------------------------------------------------------
# make_score_closer_group  (factory)
# ---------------------------------------------------------------------------
# Pénalise les changements de bâtiment entre cours consécutifs pour un groupe.
#
# Logique :
#   On cherche le cours qui précède et/ou suit immédiatement le nouveau
#   placement dans la journée du groupe. Si ce cours voisin est dans un
#   bâtiment différent, on ajoute la distance (en minutes) comme pénalité.
#
# Pourquoi une factory ?
#   Le scorer standard ne reçoit pas les bâtiments. On utilise une closure
#   pour "intégrer" buildings_map dans la fonction retournée — ainsi elle
#   reste compatible avec la signature standard (item, course, day, ...).
#
# buildings_map : dict {bat_id: Building}
# schedule      : planning courant (pour retrouver le bâtiment des voisins)
# ---------------------------------------------------------------------------
def make_score_closer_group(buildings_map: Dict[str, Building], schedule: List[ScheduleItem], dedadline_days: dict = None):
    # On construit un index (group, day) -> liste d'items triée par heure_debut
    # pour retrouver rapidement les voisins sans re-parcourir tout le planning.
    from collections import defaultdict
    day_index = defaultdict(list)
    for it in schedule:
        for g in it.group:
            day_index[(g.id, it.day)].append(it)
    for key in day_index:
        day_index[key].sort(key=lambda x: hm(x.heure_debut))

    def _travel(bat_a: str, bat_b: str) -> float:
        """Distance en minutes entre deux bâtiments (symétrique, défaut 5 min)."""
        if bat_a == bat_b:
            return 0.0
        b = buildings_map.get(bat_a)
        if b is None:
            return 5.0
        return b.dist.get(bat_b, 5.0)

    def scorer(item, course, day, hd, hf, room,
               occ_group, occ_teacher, lunch_debut_min, lunch_fin_min, deadline_days=None):
        t1, t2  = hm(hd), hm(hf)
        bat_new = room.bat
        penalty = 0.0
        for g in item.group:
            for v in day_index.get((g.id, day), []):
                vt1, vt2 = hm(v.heure_debut), hm(v.heure_fin)
                bat_v    = v.building if v.building and v.building != "?" else None
                if bat_v is None:
                    continue
                if vt2 <= t1:
                    if t1 - vt2 <= 30:
                        penalty += _travel(bat_v, bat_new)
                elif vt1 >= t2:
                    if vt1 - t2 <= 30:
                        penalty += _travel(bat_new, bat_v)

        return penalty / 60.0

    return scorer


# ---------------------------------------------------------------------------
# make_score_closer_teacher  (factory)
# ---------------------------------------------------------------------------
# Même logique pour le prof.
# ---------------------------------------------------------------------------
def make_score_closer_teacher(buildings_map: Dict[str, Building], schedule: List[ScheduleItem], deadline_days: dict = None):
    from collections import defaultdict
    day_index = defaultdict(list)
    for it in schedule:
        day_index[(it.teacher.id, it.day)].append(it)
    for key in day_index:
        day_index[key].sort(key=lambda x: hm(x.heure_debut))

    def _travel(bat_a: str, bat_b: str) -> float:
        if bat_a == bat_b:
            return 0.0
        b = buildings_map.get(bat_a)
        if b is None:
            return 5.0
        return b.dist.get(bat_b, 5.0)

    def scorer(item, course, day, hd, hf, room,
               occ_group, occ_teacher, lunch_debut_min, lunch_fin_min, deadline_days=None):
        t1, t2   = hm(hd), hm(hf)
        bat_new  = room.bat
        voisins  = day_index.get((item.teacher.id, day), [])
        penalty  = 0.0

        for v in voisins:
            vt1, vt2 = hm(v.heure_debut), hm(v.heure_fin)
            bat_v    = v.building if v.building and v.building != "?" else None
            if bat_v is None:
                continue
            if vt2 <= t1:
                gap = t1 - vt2
                if gap <= 30:
                    penalty += _travel(bat_v, bat_new)
            elif vt1 >= t2:
                gap = vt1 - t2
                if gap <= 30:
                    penalty += _travel(bat_new, bat_v)

        return penalty / 60.0

    return scorer


# ---------------------------------------------------------------------------
# make_default_scorers
# ---------------------------------------------------------------------------
# Retourne une liste de (name, fn, weight).
# Le nom sert à l'évaluation et au log ; fn+weight servent au placement.
# À appeler dans main.py après le chargement des données.
# ---------------------------------------------------------------------------
def make_default_scorers(buildings_list: List[Building],
                         schedule: List[ScheduleItem],
                         deadline_days: dict = None,
                         static_scorers: list = None,
                         closer_group_weight: float = 0.4,
                         closer_teacher_weight: float = 0.3,
                         deadline_weight: float = 1.0) -> list:
    """
    Construit la liste complète (name, fn, weight).

    deadline_days           : dict {course_id: jour_deadline} — si fourni, ajoute le scorer deadline.
    static_scorers          : [(name, fn, weight)] — si None, utilise les 4 défauts.
    closer_group_weight     : mettre à 0.0 pour désactiver le scorer closer_group.
    closer_teacher_weight   : mettre à 0.0 pour désactiver le scorer closer_teacher.
    deadline_weight         : poids du scorer deadline (la pénalité est déjà 10000, le poids n'est là que pour l'identifier).
    """
    buildings_map = {b.id: b for b in buildings_list}

    if static_scorers is None:
        static_scorers = [
            ("same_day",        score_same_day,        2.0),
            ("no_late_group",   score_no_late_group,   1.0),
            ("no_late_teacher", score_no_late_teacher, 1.0),
            ("no_gap_group",    score_no_gap_group,    0.5),
        ]

    result = list(static_scorers)
    if deadline_days:
        result.append(("deadline", make_score_deadline(deadline_days), deadline_weight))
    if closer_group_weight > 0.0:
        result.append(("closer_group",
                        make_score_closer_group(buildings_map, schedule),
                        closer_group_weight))
    if closer_teacher_weight > 0.0:
        result.append(("closer_teacher",
                        make_score_closer_teacher(buildings_map, schedule),
                        closer_teacher_weight))
    return result


# ---------------------------------------------------------------------------
# evaluate_perturbation
# ---------------------------------------------------------------------------
# Évalue la qualité d'un planning (ou d'un sous-ensemble d'items).
# Retourne un dict {"scorer_name": score_pondéré, ..., "total": score_total}.
#
# Appelé deux fois dans main.py : sur l'EDT de base et sur l'EDT perturbé.
# Le delta entre les deux mesure l'impact réel de la perturbation.
# Les occupations sont construites sur final_schedule pour avoir le
# contexte réel (voisins, trous, etc.).
# ---------------------------------------------------------------------------
def evaluate_perturbation(
    rescheduled:     List[ScheduleItem],   # items à évaluer (tout le planning ou sous-ensemble)
    final_schedule:  List[ScheduleItem],   # planning complet après résolution
    courses:         list,
    rooms:           list,
    named_scorers:   list,                 # [(name, fn, weight), ...]
    lunch_debut_min: int,
    lunch_fin_min:   int,
) -> dict:

    if not rescheduled or not named_scorers:
        return {"total": 0.0}

    course_map = {c.id: c for c in courses}
    course_map.update({str(c.id): c for c in courses})
    room_map   = {r.name: r for r in rooms}

    group_day_index, _, occ_teacher = build_occupations(final_schedule)

    scores = {name: 0.0 for name, _, _ in named_scorers}

    for item in rescheduled:
        from basics import base_course_id
        c_key = base_course_id(item.course)
        c     = course_map.get(c_key) or course_map.get(str(c_key))
        r     = room_map.get(item.room)
        if c is None or r is None:
            continue
        for name, fn, w in named_scorers:
            scores[name] += round(
                w * fn(item, c, item.day, item.heure_debut, item.heure_fin,
                        r, group_day_index, occ_teacher, lunch_debut_min, lunch_fin_min),
                2
            )

    scores["total"] = round(sum(v for k, v in scores.items() if k != "total"), 4)
    return scores


# ---------------------------------------------------------------------------
# check_deadline_violations
# ---------------------------------------------------------------------------
# Vérifie que les cours replanifiés ne dépassent pas leur deadline.
# deadline_days : dict {course_id (int): jour_limite (int, 0=lundi)}
# buffer_days   : nombre de jours minimum avant la deadline (défaut dans basics.py)
# Retourne la liste des items en violation.
# ---------------------------------------------------------------------------
def check_deadline_violations(
    rescheduled:  List[ScheduleItem],
    deadline_days: dict,
    buffer_days:   int,
) -> List[ScheduleItem]:
    from basics import base_course_id
    violations = []
    for item in rescheduled:
        cid = base_course_id(item.course)
        dl  = deadline_days.get(cid)
        if dl is None:
            try: dl = deadline_days.get(int(cid))
            except (ValueError, TypeError): pass
        if dl is not None and item.day > dl - buffer_days:
            violations.append(item)
    return violations
