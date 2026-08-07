from basics import *


# ===========================================================================
# SCÉNARIO PROF ABSENT
# ===========================================================================

def analyze_teacher_absent(schedule: List[ScheduleItem], teacher_id: str, absent_intervals: AbsentIntervals):
    """
        Analyse le planning et sépare les cours à replanifier de ceux qui restent fixes dans le cadre d'un scénario de prof absent.
    """
    to_reschedule: List[ScheduleItem] = []

    for item in schedule:
        t1, t2 = hm(item.heure_debut), hm(item.heure_fin)
        overlaps = any(
                item.day == ad and t1 < hm(ah_fin) and hm(ah_debut) < t2
                for (ad, ah_debut, ah_fin) in absent_intervals
            )
        if item.teacher.id == teacher_id and overlaps:
            to_reschedule.append(item)

    return {
            "affected": to_reschedule,
            "teacher_blocked": {teacher_id: absent_intervals},
            "rooms_blocked": {},
            "groups_blocked": {},
        }


# ===========================================================================
# SCÉNARIO SALLE INDISPONIBLE
# ===========================================================================

def analyze_room_unavailable(schedule: List[ScheduleItem], room_name: str, absent_intervals: AbsentIntervals, all_days):
    """
    Analyse le planning et sépare les cours à replanifier de ceux qui restent fixes dans le cadre d'un scénario de salle indisponible.
    """
    to_reschedule: List[ScheduleItem] = []
    all_absent: AbsentIntervals = (
        [(d, "00h00", "23h59") for d in all_days]
        if absent_intervals is None else absent_intervals
    )

    for item in schedule:
        t1, t2 = hm(item.heure_debut), hm(item.heure_fin)
        overlaps = any(
                item.day == ad and t1 < hm(ah_fin) and hm(ah_debut) < t2
                for (ad, ah_debut, ah_fin) in all_absent
            )
        if item.room == room_name and overlaps:
            to_reschedule.append(item)

    return {
            "affected": to_reschedule,
            "teacher_blocked": {},
            "rooms_blocked": {room_name: all_absent},
            "groups_blocked": {},
        }


# ===========================================================================
# SCÉNARIO LIBERATION DE CRENEAUX
# ===========================================================================

def analyze_free_slot(schedule: List[ScheduleItem], absent_intervals: AbsentIntervals, all_groups, group_ids: List[str] = None): #all_groups est un set qui contient tous les groupes de l'emploi du temps
    """
        Analyse le planning et sépare les cours à replanifier de ceux qui restent fixes dans le cadre d'un scénario de libération de créneaux.
    """
    to_reschedule: List[ScheduleItem] = []
    group_ids = group_ids if group_ids else all_groups

    for item in schedule:
        t1, t2 = hm(item.heure_debut), hm(item.heure_fin)
        overlaps = any(
                item.day == ad and t1 < hm(ah_fin) and hm(ah_debut) < t2
                for (ad, ah_debut, ah_fin) in absent_intervals
            )
        if any(g.id in group_ids for g in item.group) and overlaps:
            to_reschedule.append(item)

    return {
            "affected": to_reschedule,
            "teacher_blocked": {},
            "rooms_blocked": {},
            "groups_blocked": {g: absent_intervals for g in group_ids},
        }


# ===========================================================================
# SCÉNARIO REMPLACEMENT
# ===========================================================================

def analyze_teacher_replacement(schedule: List[ScheduleItem], all_groups, all_teachers, all_courses, absent_teacher_id: Optional[str] = None, target_course_ids: Optional[List[int]] = None, target_groups: Optional[List[str]] = None, target_session_type: Optional[str] = None, absent_intervals: Optional[AbsentIntervals] = None):
    """
        Analyse le planning et sépare les cours à replanifier de ceux qui restent fixes dans le cadre d'un scénario de remplacement ou d'affectation de prof.
    """
    to_reschedule: List[ScheduleItem] = []
    group_ids = target_groups if target_groups else all_groups
    target_course_ids = target_course_ids if target_course_ids else list(all_courses)

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

        affected.append(item)

    return {
            "affected": affected,
            "teacher_blocked": {},
            "rooms_blocked": {},
            "groups_blocked": {g: absent_intervals for g in group_ids},
        }