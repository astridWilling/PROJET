from typing import NamedTuple, List ; from ortools.sat.python import cp_model
from dataclasses import dataclass
import os

HERE = os.path.dirname(os.path.abspath(__file__))



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
    
    def apply(self,
              model: cp_model.CpSolver,
              slot: dict,
              time: dict,
              var_room: dict,
              courses: List[Course],
              groups: List[str],
              teachers: List[Teacher],
              courses_by_group:dict,
              courses_by_teacher: dict,
              rooms: List[Room],
              nb_days: int,
              nb_slots_per_day: int,
              buildings: List[Building]=None
              ) -> List[int]:
        pass

# Variables du problèmes
class Teacher(NamedTuple):
    """Professeur"""
    id : str #a terme plutot un int
    name : str
    courses : List[int]  #Que les coursid dans la liste, on fera une fonction cours.id->cours.name et une autre cours.name->cours.id (via un json/dict i guess?)

class Course(NamedTuple):
    """Cours"""
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
    """Salle"""
    name: str
    capacity: int
    room_types : List[str]
    bat: str #id du batiment auquel elle appartient

# Emploi du temps
class ScheduleItem(NamedTuple):
    """Item d'emploi du temsp"""
    course: int
    group: str
    teacher: Teacher
    day: int
    slot: int
    room: str

# Batiment
class Building(NamedTuple):
    """Batiment"""
    id: str
    name: str
    rooms: List[Room]
    dist: dict[str, float]   #nom_batiment: distance de ce batiment au batiment nom_batiment
