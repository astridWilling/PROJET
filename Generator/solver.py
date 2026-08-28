from ortools.sat.python import cp_model
from typing import List, Tuple
from basics import Course, Teacher, Room, NoSolution, TimeOut, Constraint, Building


class BestSolutionCallback(cp_model.CpSolverSolutionCallback):
    """
    Enregistre chaque nouvelle meilleure solution trouvée : (wall_time_s, objective).
    Utilisé pour tracer la courbe de convergence score vs temps.
    """
    def __init__(self):
        super().__init__()
        self._solutions = []

    def on_solution_callback(self):
        """Appelé par CP-SAT à chaque nouvelle solution trouvée. Enregistre le score courant."""
        self._solutions.append((self.WallTime(), self.ObjectiveValue()))

    @property
    def solutions(self):
        """Liste des scores enregistrés à chaque solution intermédiaire trouvée par CP-SAT."""
        return self._solutions


def solve(courses: List[Course], 
          rooms: List[Room], 
          nb_days: int, 
          lunch_slots: List[int]=[2,3,4], 
          nb_slots_per_day: int =10, 
          constraints: List[Constraint]=None, 
          timeout:int=60, 
          record_callbacks:bool=False, 
          buildings:List[Building]=None, 
          num_workers:int=4
          ) -> Tuple[cp_model.CpSolver, dict, dict, dict, str, float, int, List[BestSolutionCallback] ]:
    """
    Solveur hebdomadaire.

    constraints : listes des contraintes
    timeout : durée de recherche accordée au solveur
    record_callback : si True, garde en mémoire toutes les solutions trouvées par le solveur lors de sa recherche (pour une étude de convergence généralement)
    num_workers : nombre de coeurs CPU mis à disposition du solveur

    Retourne (solver, slot, time, room_var, solver.StatusName(status), score, max_searchtime, callbacks):
      - solver : le solveur
      - slot : dict tel que slot[(c.id, i)]   → entier dans [0, |T|×|R| - 1]   encodant (time, room)
      - time : dict tel que time[(c.id, i)]   → entier dans [0, |T| - 1]     = créneau absolu
      - room_var : dict tel que room_var[(c.id, i)] → entier dans [0, |R| - 1]   = index dans la liste rooms[]
      - solver.StatusName(status) : statut du solver après résolution
      - score : score de la meilleure solution trouvée par le solveur
      - max_searchtime : timeout, temps de recherche maximal donné au solveur
      - callbacks : liste des solutions trouvées par le solveur

    """

    courses_by_group = {}
    courses_by_teacher = {}

    for c in courses:
        courses_by_group.setdefault(c.group, []).append(c)
        courses_by_teacher.setdefault(c.teacher.id, []).append(c)

    groups = list(courses_by_group.keys())
    teachers = list(courses_by_teacher.keys())


    model = cp_model.CpModel()
    
################# Ancienne manière de faire
    # X = {} # variables sur problèmes

    # # On établit les variables du problème
    # for c in courses:
    #     for d in range(nb_days):
    #         for s in range(nb_slots_per_day):
    #             for r in rooms:
    #                 X[(c.id, d, s, r.name)] = model.NewBoolVar(f"x_{c.id}_{d}_{s}_{r.name}")

        
    #Respecter la capacité et le type des salles utilisées
    # for c in courses:
    #     for d in range(nb_days):
    #         for s in range(nb_slots_per_day):
    #             for r in rooms:
    #                 if (r.capacity < c.headcount) or (not any(rt in c.room_types for rt in r.room_types)):
    #                     model.Add(X[(c.id, d, s, r.name)] == 0)

    # Chaque cours placé le bon nombre de fois
    # for c in courses:
    #     model.Add(sum(X[(c.id, d, s, r.name)] for d in range(nb_days) for s in range(nb_slots_per_day) for r in rooms) == c.slots_per_week)

    # Chaque groupe a au plus un cours par période
    # for g in groups:
    #     for d in range(nb_days):
    #         for s in range(nb_slots_per_day):
    #             model.Add(sum(X[(c.id, d, s, r.name)] for c in courses_by_group[g] for r in rooms) <= 1)

    # Chaque salle a au plus un cours
    # for r in rooms:
    #     for d in range(nb_days):
    #         for s in range(nb_slots_per_day):
    #             model.Add(sum(X[c.id, d, s, r.name] for c in courses) <= 1)
    
    # Chaque prof a au plus 1 cours par période
    # for teacher in teachers:
    #     for d in range(nb_days):
    #         for s in range(nb_slots_per_day):
    #             model.Add(sum(X[(c.id, d, s, r.name)] for c in courses_by_teacher[teacher] for r in rooms) <= 1)

    # Au moins une période libre parmi les lunch_slots pour chaque groupe
    # for g in groups:
    #     for d in range(nb_days):
    #         model.Add(sum(X[(c.id, d, s, r.name)] for c in courses_by_group[g] for s in lunch_slots for r in rooms) <= len(lunch_slots)-1)
    
    
    slot = {}

    nb_timeslots = nb_days * nb_slots_per_day
    nb_rooms = len(rooms)

    for c in courses:
        for i in range(c.slots_per_week):
            key = (c.id, i)

            slot[key] = model.NewIntVar(
                0,
                nb_timeslots * nb_rooms - 1,
                f"slot_{c.id}_{i}"
            ) # On maintenant une variable par session, chaque valeur encode (time,room)

    time = {}
    room_var = {}

    #############################
    #### CONTRAINTES NATIVES ####
    #############################
    # Créer les variables et restreindre le domaine des salles valides dès la création
    for c in courses:
        valid_rooms = [
            r_id for r_id, r in enumerate(rooms)
            if r.capacity >= c.headcount and any(rt in c.room_types for rt in r.room_types)
        ]
        if not valid_rooms:
            raise ValueError(f"Aucune salle valide pour cours {c.name} : room_types={c.room_types}, headcount={c.headcount}")

        room_domain = cp_model.Domain.FromValues(valid_rooms)

        for i in range(c.slots_per_week):
            key = (c.id, i)
            time[key] = model.NewIntVar(0, nb_timeslots - 1, f"time_{c.id}_{i}")
            room_var[key] = model.NewIntVarFromDomain(room_domain, f"room_{c.id}_{i}")
            model.Add(slot[key] == time[key] * nb_rooms + room_var[key])
       

    # Chaque cours ne peut pas avoir deux sessions en même temps
    for c in courses:
        if c.slots_per_week > 1:
            model.AddAllDifferent([time[(c.id, i)] for i in range(c.slots_per_week)])

    # Pas deux cours en même temps pour un même groupe
    for g in groups:
        sessions_g = [(c, i) for c in courses_by_group[g] for i in range(c.slots_per_week)]
        if len(sessions_g) > 1:
            model.AddAllDifferent([time[(c.id, i)] for c, i in sessions_g])

    # Pas deux cours dans une même salle
    model.AddAllDifferent(slot.values())

    # Chaque prof a au plus 1 cours par période
    for t in teachers:
        sessions_t = [(c, i) for c in courses_by_teacher[t] for i in range(c.slots_per_week)]
        if len(sessions_t) > 1:
            model.AddAllDifferent([time[(c.id, i)] for c, i in sessions_t])
    # Au moins une période libre parmi les lunch_slots pour chaque groupe
    for g in groups:
        sessions_g = [(c, i) for c in courses_by_group[g] for i in range(c.slots_per_week)]

        for d in range(nb_days):
            lunch_times = [d * nb_slots_per_day + s for s in lunch_slots]

            indicators = []

            for c, i in sessions_g:
                t_expr = time[(c.id, i)]

                b = model.NewBoolVar(f"lunch_{c.id}_{i}_{d}")

                # b = 1 → t ∈ lunch_times
                model.AddAllowedAssignments([t_expr], [[t] for t in lunch_times]).OnlyEnforceIf(b)

                # b = 0 → t ∉ lunch_times
                model.AddForbiddenAssignments([t_expr], [[t] for t in lunch_times]).OnlyEnforceIf(b.Not())

                indicators.append(b)

            model.Add(sum(indicators) <= len(lunch_times) - 1)
    #############################################
    #### Gestion des contraintes non natives ####
    #############################################
    penalties = []
    if constraints:
        for c in constraints:
            if not c.is_active:
                continue

            if c.is_hard:
                # Correction : time et room_var étaient manquants dans l'appel précédent,
                # ce qui causait un crash silencieux dès la première contrainte souple
                c.apply(model, slot, time, room_var, courses, groups, teachers, courses_by_group, courses_by_teacher, rooms, nb_days, nb_slots_per_day, buildings=buildings)
            else:
                penalties.extend(c.apply(model, slot, time, room_var, courses, groups, teachers, courses_by_group, courses_by_teacher, rooms, nb_days, nb_slots_per_day, buildings=buildings))

    if penalties:
        model.Minimize(sum(penalties))

    # Stratégie de branchement : first-fail
    # CP-SAT choisit en priorité la variable time dont le domaine résiduel est le plus petit
    # (= session avec le moins de créneaux disponibles) et essaie la valeur minimale en premier.
    # Sur les grosses instances, cela réduit drastiquement le temps pour trouver une 1ère solution réalisable.
    model.AddDecisionStrategy(
        list(time.values()),
        cp_model.CHOOSE_MIN_DOMAIN_SIZE,
        cp_model.SELECT_MIN_VALUE
    )

    # Solveur
    solver = cp_model.CpSolver()

    max_searchtime = timeout  # En secondes! -> le solver s'arrete autour des 60s ; plus l'instance est grosse, plus il va dépasser les 60s
    solver.parameters.max_time_in_seconds = max_searchtime  # Safety net => si pas de solution, timeout 
                                                                    #=> renvoie la dernière solution feasible si possible (status=FEASIBLE)
                                                                        # OU si pas de solution feasible trouvée avant, status=UNKNOWN et ne renvoie rien
    solver.parameters.num_search_workers = num_workers
    
    # Solve
    cb = BestSolutionCallback() if record_callbacks else None
    status = solver.Solve(model, cb) if cb else solver.Solve(model)

    if solver.StatusName(status) in ["OPTIMAL", "FEASIBLE"]:
        score = solver.ObjectiveValue()
    else:
        score = None

    callbacks = cb.solutions if cb else None

    return solver, slot, time, room_var, solver.StatusName(status), score, max_searchtime, callbacks