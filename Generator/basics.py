from typing import NamedTuple, List
from dataclasses import dataclass

# Erreurs
class NoSolution(Exception):
    pass

class TimeOut(Exception):
    pass

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

# Variables du problèmes
class Teacher(NamedTuple):
    id : str
    name : str
    courses : List[int]  #Que les coursid dans la liste, on fera une fonction cours.id->cours.name et une autre cours.name->cours.id (via un json/dict i guess?)

class Course(NamedTuple):
    id: int
    name : str
    teacher: Teacher
    group: str
    headcount : int  #Nombre d'étudiants dans le groupe qui suit ce cours
    room_types : List[str]  #! PEUT-ETRE AJOUTER PLUS TARD UN ORDRE DE PRIORITE->si ["TD","CM"], on préfère prendre une salle plutot TD (définie avec ["TD","CM"] aussi) plutot qu'une salle CM (définie avec ["CM","TD"])
    slots_per_week: int
    # Optionnel — uniquement utile en mode semestre.
    # Mappe type de session → room_types requis pour cette session.
    # Ex: {"CM": ["CM"], "TD": ["TD"], "TP": ["INFO"]}
    # Si None, on utilise room_types pour toutes les sessions (comportement existant).
    session_room_types: dict = None
    # Optionnel — préférence de placement sur le semestre.
    # "early"  : pousse les sessions vers le début du semestre
    # "late"   : pousse les sessions vers la fin
    # "middle" : pousse les sessions vers le milieu
    # None     : pas de préférence (comportement par défaut)
    ordering_preference: str = None

class Room(NamedTuple):
    name: str
    capacity: int
    room_types : List[str]
    bat: str #id du batiment auquel elle appartient

# Emploi du temps
class ScheduleItem(NamedTuple):
    course: int
    group: str
    teacher: Teacher
    day: int
    slot: int
    room: str

# Batiment
class Building(NamedTuple):
    id: str
    name: str
    rooms: List[Room]
    dist: dict[str, float]   #nom_batiment: distance de ce batiment au batiment nom_batiment
