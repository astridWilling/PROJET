from typing import NamedTuple, List
import os, json, csv, datetime, uuid
from collections import defaultdict
from typing import List, Tuple, Set, Optional, Callable
import re as _re
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Variables globales (et plus bas)
# ---------------------------------------------------------------------------
HERE = os.path.dirname(os.path.abspath(__file__))
EDT_DIR = os.path.join(HERE, "edt")
LUNCH_MIN_FREE_MINUTES = 60  # Durée minimale de pause midi garantie (contrainte dure)
SLOT_TABLE = ["08h00", "09h30", "11h00", "12h15", "13h00", "14h00", "15h30", "17h00"] #Table des créneaux horaires (pour HTML et scoring uniquement)
NB_SLOTS   = len(SLOT_TABLE)
MAX_HOURS_BY_TYPE: dict = {
    "MC":      196.0,
    "Thesard":  96.0,
    "Externe":  72.0,
    "Mi-temps": 48.0,
} # Heures max par défaut selon le statut du prof
DEADLINE_BUFFER_DAYS  = 3   # nombre de jours min entre le dernier cours et l'exam
MIN_DAY = -1


# --------------------------------------------------------------------------
# Classes
# --------------------------------------------------------------------------

class Teacher(NamedTuple):
    id:               str           #! Passer en int
    name:             str
    courses:          List[int]
    teacher_type:     str   = None  # "MC", "Thesard", "Externe", ...
    max_hours:        float = None  # override du quota du type ; None → MAX_HOURS_BY_TYPE
    possible_classes: dict  = None  # {course_id: adequacy_score 0.0–1.0}
    dept:             str   = None  # id du département

class Group(NamedTuple):
    id:           str                       # "1_C"
    headcount:    int                       # 30, 35...
    parent:       "Group"        = None     # objet Group parent — None pour les groupes racines
    subgroup_ids: Optional[List[str]] = None  # ["1_C_a", "1_C_b"] — None si pas de sous-groupes

    def ancestors(self) -> List[str]:
        """Retourne [self.id, parent.id, grand-parent.id, ...] en remontant la hiérarchie."""
        result = [self.id]
        curr = self.parent
        while curr:
            result.append(curr.id)
            curr = curr.parent
        return result

class Course(NamedTuple):
    id: int
    name : str
    teacher: Teacher
    group_ids: List[str] #! Passer en List[int] ?
    room_types : List[str]
    slots_per_week: int
    session_room_types: dict = None
    ordering_preference: str = None
    dept: str = None  # id du département
    preferred_buildings: List[str] = []  # bâtiments préférés (soft constraint)

class Department(NamedTuple):
    """Regroupe profs et cours par département pour filtrer les candidats au remplacement."""
    id:          str
    name:        str
    teacher_ids: List[str]  # ids pour éviter les références circulaires  #! Passer en List[int] ?
    course_ids:  List[int]

class Room(NamedTuple): #! Rajouter une id pour chaque salle (int) et garder le name pour l'affichage ?
    name: str
    capacity: int
    room_types : List[str]
    bat: str

class Building(NamedTuple):
    id: str                  #! Passer en int et garder le name pour l'affichage ?
    name: str
    rooms: List[Room]
    dist: dict[str, float]   #nom_batiment: distance de ce batiment au batiment nom_batiment

class ScheduleItem(NamedTuple):
    course: int
    group: List["Group"]
    teacher: Teacher
    day: int
    heure_debut: str   # "09h30"
    heure_fin:   str   # "11h00"
    room: str
    building:     str = None
    session_type: str = None  # "CM", "TD", "TP", "Sport" — type de la séance

# Base contraintes
@dataclass
class Constraint:
    is_hard: bool
    is_active: bool
    weight: int
    lunch_slots: List[int]
    nb_slots_per_day: int
    
    def apply(self, model, slot, time, var_room, courses, groups, teachers, courses_by_group, courses_by_teacher, rooms, nb_days, nb_slots_per_day, buildings=None):
        pass
# ---------------------------------------------------------------------------
# Alias de types
# ---------------------------------------------------------------------------
# Occupation : (entité, jour, minute)
OccKey      = Tuple[str, int, int]
OccGroup    = Set[OccKey]
OccRoom     = Set[OccKey]
OccTeacher  = Set[OccKey]

# Absence : (jour, heure_debut, heure_fin)
AbsentInterval  = Tuple[int, str, str]
AbsentIntervals = List[AbsentInterval]

Scorer     = Callable[..., float]
ScorerList = List[Tuple[Scorer, float]]


# ---------------------------------------------------------------------------
# Fonctions utilitaires
# ---------------------------------------------------------------------------
def hm(h: str) -> int:
    """'09h30' → 570  (minutes depuis minuit).
    Robuste : '7h' → 420, '17h3' → 1023, '9h30' → 570.
    """
    parts = h.split("h")
    hh = parts[0]
    mm = parts[1] if len(parts) > 1 and parts[1] else "0"
    if len(mm) == 1:
        mm = mm + "0"   # '17h3' → mm='3' → '30'
    return int(hh) * 60 + int(mm)

def min_to_hm(minutes: int) -> str:
    """570 → '09h30'"""
    return f"{minutes // 60:02d}h{minutes % 60:02d}"

######### Variables globales suite ##########
LATE_COURSE_MAX = hm("17h00") # Heure maximale de fin de cours acceptable (configurable selon l'établissement)
_SLOT_MIN = [hm(s) for s in SLOT_TABLE]
#############################################

def heure_to_slot(h: str) -> int:
    """Retourne l'indice SLOT_TABLE le plus proche ≤ h (pour HTML)."""
    m = hm(h)
    idx = 0
    for i, sm in enumerate(_SLOT_MIN):
        if sm <= m:
            idx = i
    return idx

def duration_in_slots(hdebut: str, hfin: str) -> int:
    """Nombre de lignes SLOT_TABLE couvertes (pour HTML uniquement)."""
    start, end = hm(hdebut), hm(hfin)
    count = 0
    for i, sm in enumerate(_SLOT_MIN):
        next_sm = _SLOT_MIN[i + 1] if i + 1 < NB_SLOTS else sm + 75
        if sm < end and next_sm > start:
            count += 1
    return max(1, count)

def base_course_id(cid):
    m = _re.match(r'^(.+)_w\d+_s\d+$', str(cid))
    return m.group(1) if m else cid

def to_abs_day(week: int, day: int):
    return week*5 + day

def from_abs_day(abs_day: int):
    return abs_day//5, abs_day%5

_JOURS_COURTS = ["Lun", "Mar", "Mer", "Jeu", "Ven"]

def fmt_abs_day(d: int) -> str:
    """Formate un jour absolu : 'S3 Mer (J12)'."""
    return f"S{d // 5 + 1} {_JOURS_COURTS[d % 5]} (J{d})"