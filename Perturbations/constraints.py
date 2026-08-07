from basics import Constraint


ALL_CONSTRAINTS = {}


CONSTRAINT_ABBR = {
    "LongLunch": "ll",
    "LongLunchTeacher": "llT",
    "NoGap": "nogap",
    "NoLateDay": "nld",
    "NoLateDayTeacher": "nldT",
    "Closer": "c",
    "CloserTeacher": "cT"
}

def register(cls):
    ALL_CONSTRAINTS[cls.__name__] = cls
    return cls



def activate(c: Constraint):
    c.is_active = True

def deactivate(c: Constraint):
    c.is_active = False

def harden(c: Constraint):
    c.is_hard = True

def soften(c: Constraint):
    c.is_hard = False


#################
##### NOTES #####
#################

# slot[(c.id, i)]   → entier dans [0, |T|×|R| - 1]   encodant (time, room)
# time[(c.id, i)]   → entier dans [0, |T| - 1]         = créneau absolu
# var_room[(c.id, i)] → entier dans [0, |R| - 1]       = index dans la liste rooms[]

# Pour récupérer la Room Python :  rooms[ var_room[(c.id,i)].value ]  → UNIQUEMENT après résolution
# Pendant la modélisation → utiliser AddElement pour lire rooms[var_room[(c.id,i)]]



##############################
#### CONTRAINTES ETUDIANTS ###
##############################

@register
class LongLunch(Constraint):

    def __init__(self, is_hard=False, is_active=True, weight=3, lunch_slots=None, nb_slots_per_day=10):
        super().__init__(is_hard=is_hard, is_active=is_active, weight=weight, lunch_slots=lunch_slots, nb_slots_per_day=nb_slots_per_day)

    def apply(self, model, slot, time, var_room, courses, groups, teachers, courses_by_group, courses_by_teacher, rooms, nb_days, nb_slots_per_day, buildings=None):
        penalties = []

        if  len(self.lunch_slots)<=4:  # On pénalise le nb de transitions cours/libre pour en avoir le moins possible
            for g in groups:
                sessions_g = [(c,i) for c in courses_by_group[g] for i in range(c.slots_per_week)]

                for d in range(nb_days):
                    transitions = []

                    for i in range(1, len(self.lunch_slots)):
                        s_prev = self.lunch_slots[i-1]
                        s = self.lunch_slots[i]

                        t_prev = d * self.nb_slots_per_day + s_prev
                        t_curr = d * self.nb_slots_per_day + s

                        prev_occ = []
                        curr_occ = []

                        for c,i_session in sessions_g:
                            b_prev = model.NewBoolVar(f"ll_prev_{c.id}_{i_session}_{d}_{s}")
                            model.Add(time[(c.id, i_session)] == t_prev).OnlyEnforceIf(b_prev)
                            model.Add(time[(c.id, i_session)] != t_prev).OnlyEnforceIf(b_prev.Not()) #! CP-SAT peut ne pas bien gérer le !=

                            b_curr = model.NewBoolVar(f"ll_curr_{c.id}_{i_session}_{d}_{s}")
                            model.Add(time[(c.id, i_session)] == t_curr).OnlyEnforceIf(b_curr)
                            model.Add(time[(c.id, i_session)] != t_curr).OnlyEnforceIf(b_curr.Not()) #! CP-SAT peut ne pas bien gérer le !=

                            prev_occ.append(b_prev)
                            curr_occ.append(b_curr)

                        diff = model.NewBoolVar(f"diff_{g}_{d}_{s}")

                        # diff ↔ (prev_sum != curr_sum)
                        # On évite le != sur des sommes en passant par la valeur absolue de la différence :
                        # |prev_sum - curr_sum| >= 1 ↔ prev_sum != curr_sum
                        n_sess = len(sessions_g)
                        delta = model.NewIntVar(-n_sess, n_sess, f"delta_{g}_{d}_{s}")
                        abs_delta = model.NewIntVar(0, n_sess, f"abs_delta_{g}_{d}_{s}")
                        model.Add(delta == sum(prev_occ) - sum(curr_occ))
                        model.AddAbsEquality(abs_delta, delta)
                        model.Add(abs_delta >= 1).OnlyEnforceIf(diff)   # diff=1 → sommes différentes
                        model.Add(abs_delta == 0).OnlyEnforceIf(diff.Not())  # diff=0 → sommes égales

                        transitions.append(diff)

                    penalties.append(self.weight * sum(transitions))
        else:   # On pénalise si il n'y a qu'un slot de libre dans les lunch_slots
            target = len(self.lunch_slots) - 1

            for g in groups:
                sessions_g = [(c, i) for c in courses_by_group[g] for i in range(c.slots_per_week)]

                for d in range(nb_days):
                    lunch_times = [d * self.nb_slots_per_day + s for s in self.lunch_slots]

                    indicators = []

                    for c, i in sessions_g:
                        b = model.NewBoolVar(f"ll_count_{c.id}_{i}_{d}")

                        # b = 1 ⇔ session est dans lunch
                        model.AddAllowedAssignments([time[(c.id, i)]], [[t] for t in lunch_times]).OnlyEnforceIf(b)
                        model.AddForbiddenAssignments([time[(c.id, i)]], [[t] for t in lunch_times]).OnlyEnforceIf(b.Not())

                        indicators.append(b)

                    is_bad = model.NewBoolVar(f"long_lunch_{g}_day{d}")

                    # is_bad ↔ (nb_courses == target)
                    # Même technique : on passe par |sum(indicators) - target| pour éviter le !=
                    n_sess = len(sessions_g)
                    delta_nb = model.NewIntVar(-n_sess, n_sess, f"delta_nb_{g}_{d}")
                    abs_nb = model.NewIntVar(0, n_sess, f"abs_nb_{g}_{d}")
                    model.Add(delta_nb == sum(indicators) - target)
                    model.AddAbsEquality(abs_nb, delta_nb)
                    model.Add(abs_nb == 0).OnlyEnforceIf(is_bad)       # is_bad=1 → nb == target
                    model.Add(abs_nb >= 1).OnlyEnforceIf(is_bad.Not()) # is_bad=0 → nb != target

                    penalties.append(self.weight * is_bad)
        return penalties


@register
class NoGap(Constraint):

    def __init__(self, is_hard=False, is_active=True, weight=3, lunch_slots=None, nb_slots_per_day=10):
        super().__init__(is_hard=is_hard, is_active=is_active, weight=weight, lunch_slots=lunch_slots, nb_slots_per_day=nb_slots_per_day)

    def apply(self, model, slot, time, var_room, courses, groups, teachers, courses_by_group, courses_by_teacher, rooms, nb_days, nb_slots_per_day, buildings=None):
        penalties = []

        for g in groups:
            sessions_g = [(c, i) for c in courses_by_group[g] for i in range(c.slots_per_week)]

            for d in range(nb_days):
                # Étape 1 : calculer une BoolVar d'occupation agrégée pour CHAQUE slot du jour.
                # occ[s] = 1 ssi au moins une session du groupe g est placée au slot absolu (d*nb_slots + s).
                # Clé de l'optimisation : on crée ces variables UNE SEULE FOIS par slot et on les RÉUTILISE
                # pour tous les gaps qui les impliquent (s-1 prev, s curr, s+1 next).
                # Avant, chaque gap recréait 3 × |sessions| BoolVars ; maintenant c'est 1 BoolVar par slot.
                occ = {}
                for s in range(self.nb_slots_per_day):
                    t_abs = d * self.nb_slots_per_day + s
                    at_s = []
                    for c, i in sessions_g:
                        # bv = 1 ssi la session (c, i) est placée exactement à ce slot
                        bv = model.NewBoolVar(f"at_{g}_{d}_{s}_{c.id}_{i}")
                        model.Add(time[(c.id, i)] == t_abs).OnlyEnforceIf(bv)
                        model.Add(time[(c.id, i)] != t_abs).OnlyEnforceIf(bv.Not())
                        at_s.append(bv)
                    # occ_s = OR de tous les bv : le slot est occupé si au moins une session y est
                    occ_s = model.NewBoolVar(f"occ_{g}_{d}_{s}")
                    model.Add(sum(at_s) >= 1).OnlyEnforceIf(occ_s)
                    model.Add(sum(at_s) == 0).OnlyEnforceIf(occ_s.Not())
                    occ[s] = occ_s

                # Étape 2 : détecter les gaps (trou dans l'emploi du temps)
                # Un gap au slot s = slot s-1 occupé ET slot s libre ET slot s+1 occupé
                # On utilise AddBoolAnd/AddBoolOr sur les BoolVars agrégés : pas de != sur des sommes
                for s in range(1, self.nb_slots_per_day - 1):
                    if s - 1 in self.lunch_slots or s in self.lunch_slots or s + 1 in self.lunch_slots:
                        continue

                    gap = model.NewBoolVar(f"gap_{g}_{d}_{s}")
                    # gap=1 → les 3 conditions sont vraies simultanément
                    model.AddBoolAnd([occ[s - 1], occ[s].Not(), occ[s + 1]]).OnlyEnforceIf(gap)
                    # gap=0 → au moins une des 3 conditions est fausse (De Morgan)
                    model.AddBoolOr([occ[s - 1].Not(), occ[s], occ[s + 1].Not()]).OnlyEnforceIf(gap.Not())

                    penalties.append(self.weight * gap)

        return penalties


@register
class NoLateDay(Constraint):
    def __init__(self, is_hard=False, is_active=True, weight=3, lunch_slots=None, nb_slots_per_day=10):
        super().__init__(is_hard=is_hard, is_active=is_active, weight=weight, lunch_slots=lunch_slots, nb_slots_per_day=nb_slots_per_day)

    def apply(self, model, slot, time, var_room, courses, groups, teachers, courses_by_group, courses_by_teacher, rooms, nb_days, nb_slots_per_day, buildings=None):
        penalties = []

        for g in groups:
            for d in range(nb_days):
                last_slots = [self.nb_slots_per_day-2, self.nb_slots_per_day-1]

                for s in last_slots:
                    t = d * self.nb_slots_per_day + s

                    for c in courses_by_group[g]:
                        for i in range(c.slots_per_week):
                            b = model.NewBoolVar(f"late_{c.id}_{i}_{d}_{s}")

                            model.Add(time[(c.id, i)] == t).OnlyEnforceIf(b)
                            model.Add(time[(c.id, i)] != t).OnlyEnforceIf(b.Not())

                            penalties.append(self.weight * b)

        return penalties
    

@register
class Closer(Constraint):
    def __init__(self, is_hard=False, is_active=True, weight=3, lunch_slots=None, nb_slots_per_day=10, threshold=5):
        super().__init__(is_hard=is_hard, is_active=is_active, weight=weight, lunch_slots=lunch_slots, nb_slots_per_day=nb_slots_per_day)
        self.threshold = threshold  # distance en minutes au-delà de laquelle on pénalise

    # slot[(c.id, i)]   → entier dans [0, |T|×|R| - 1]   encodant (time, room)
    # time[(c.id, i)]   → entier dans [0, |T| - 1]         = créneau absolu
    # var_room[(c.id, i)] → entier dans [0, |R| - 1]       = index dans la liste rooms[]

    def apply(self, model, slot, time, var_room, courses, groups, teachers, courses_by_group, courses_by_teacher, rooms, nb_days, nb_slots_per_day, buildings=None):
        if not buildings:
            return []

        nb_r   = len(rooms)
        nb_bat = len(buildings)
        bat_by_id  = {b.id: b   for b in buildings}
        bat_index  = {b.id: idx for idx, b in enumerate(buildings)}

        # room_to_bat[r] = index du bâtiment de la salle r  (taille nb_r, ex: 40)
        room_to_bat = [bat_index[rooms[r].bat] for r in range(nb_r)]

        # Table de distance entre bâtiments : nb_bat² = 25 entrées (était nb_r²=1600)
        exceeds_bat_flat = [
            1 if bat_by_id[buildings[b1].id].dist.get(buildings[b2].id, 0) > self.threshold else 0
            for b1 in range(nb_bat) for b2 in range(nb_bat)
        ]

        # bat_var[(c.id, i)] = bâtiment de la salle assignée à la session i du cours c.
        # AddElement(var_room, room_to_bat, bat_var) : table de taille nb_r=40, trivial.
        bat_var = {}
        for c in courses:
            for i in range(c.slots_per_week):
                bv = model.NewIntVar(0, nb_bat - 1, f"cbat_{c.id}_{i}")
                model.AddElement(var_room[(c.id, i)], room_to_bat, bv)
                bat_var[(c.id, i)] = bv

        at_cache = {}

        def is_at(c_id, i, t_abs):
            key = (c_id, i, t_abs)
            if key not in at_cache:
                b = model.NewBoolVar(f"cat_{c_id}_{i}_{t_abs}")
                model.Add(time[(c_id, i)] == t_abs).OnlyEnforceIf(b)
                model.Add(time[(c_id, i)] != t_abs).OnlyEnforceIf(b.Not())
                at_cache[key] = b
            return at_cache[key]

        penalties = []
        for g in groups:
            sessions_g = [(c, i) for c in courses_by_group[g]
                          for i in range(c.slots_per_week)]

            # Pré-filtrage : si tous les bâtiments possibles pour ce groupe sont
            # à distance <= threshold entre eux, aucune pénalité ne peut se déclencher.
            possible_bats_g = {
                bat_index[r.bat]
                for c in courses_by_group[g]
                for r in rooms
                if any(rt in r.room_types for rt in c.room_types)
            }
            if not any(
                exceeds_bat_flat[b1 * nb_bat + b2]
                for b1 in possible_bats_g for b2 in possible_bats_g
            ):
                continue

            for d in range(nb_days):
                # bat_at[s] = bâtiment du groupe g au slot s  (domaine 0..nb_bat-1)
                bat_at = {}
                occ    = {}
                for s in range(nb_slots_per_day):
                    t_abs  = d * nb_slots_per_day + s
                    bat_s  = model.NewIntVar(0, nb_bat - 1, f"cbat_at_{g}_{d}_{s}")
                    bat_at[s] = bat_s
                    at_s = []
                    for c, i in sessions_g:
                        b_at = is_at(c.id, i, t_abs)
                        model.Add(bat_s == bat_var[(c.id, i)]).OnlyEnforceIf(b_at)
                        at_s.append(b_at)
                    occ_s = model.NewBoolVar(f"cocc_{g}_{d}_{s}")
                    model.Add(sum(at_s) >= 1).OnlyEnforceIf(occ_s)
                    model.Add(sum(at_s) == 0).OnlyEnforceIf(occ_s.Not())
                    occ[s] = occ_s

                for s in range(nb_slots_per_day - 1):
                    # comb_bat encode la paire de bâtiments : domaine 0..nb_bat²-1 = 0..24
                    # (était 0..nb_r²-1 = 0..1599 → table AddElement 64× plus petite)
                    comb_bat = model.NewIntVar(0, nb_bat * nb_bat - 1, f"ccomb_{g}_{d}_{s}")
                    model.Add(comb_bat == bat_at[s] * nb_bat + bat_at[s + 1])
                    b_thr = model.NewBoolVar(f"cbthr_{g}_{d}_{s}")
                    model.AddElement(comb_bat, exceeds_bat_flat, b_thr)

                    b_pen = model.NewBoolVar(f"cpen_{g}_{d}_{s}")
                    model.AddBoolAnd([occ[s], occ[s + 1], b_thr]).OnlyEnforceIf(b_pen)
                    model.AddBoolOr([occ[s].Not(), occ[s + 1].Not(), b_thr.Not()]).OnlyEnforceIf(b_pen.Not())
                    penalties.append(self.weight * b_pen)

        return penalties


################################
#### CONTRAINTES PROFESSEURS ###
################################

@register
class LongLunchTeacher(Constraint):

    def __init__(self, is_hard=False, is_active=True, weight=3, lunch_slots=None, nb_slots_per_day=10):
        super().__init__(is_hard=is_hard, is_active=is_active, weight=weight, lunch_slots=lunch_slots, nb_slots_per_day=nb_slots_per_day)

    def apply(self, model, slot, time, var_room, courses, groups, teachers, courses_by_group, courses_by_teacher, rooms, nb_days, nb_slots_per_day, buildings=None):
        penalties = []

        if  len(self.lunch_slots)<=4:  # On pénalise le nb de transitions cours/libre pour en avoir le moins possible
            for teach in teachers:
                sessions_teach = [(c,i) for c in courses_by_teacher[teach] for i in range(c.slots_per_week)]

                for d in range(nb_days):
                    transitions = []

                    for i in range(1, len(self.lunch_slots)):
                        s_prev = self.lunch_slots[i-1]
                        s = self.lunch_slots[i]

                        t_prev = d * self.nb_slots_per_day + s_prev
                        t_curr = d * self.nb_slots_per_day + s

                        prev_occ = []
                        curr_occ = []

                        for c,i_session in sessions_teach:
                            b_prev = model.NewBoolVar(f"ll_prev_{c.id}_{i_session}_{d}_{s}")
                            model.Add(time[(c.id, i_session)] == t_prev).OnlyEnforceIf(b_prev)
                            model.Add(time[(c.id, i_session)] != t_prev).OnlyEnforceIf(b_prev.Not()) #! CP-SAT peut ne pas bien gérer le !=

                            b_curr = model.NewBoolVar(f"ll_curr_{c.id}_{i_session}_{d}_{s}")
                            model.Add(time[(c.id, i_session)] == t_curr).OnlyEnforceIf(b_curr)
                            model.Add(time[(c.id, i_session)] != t_curr).OnlyEnforceIf(b_curr.Not()) #! CP-SAT peut ne pas bien gérer le !=

                            prev_occ.append(b_prev)
                            curr_occ.append(b_curr)

                        diff = model.NewBoolVar(f"diff_{teach}_{d}_{s}")

                        # Même encodage que LongLunch : diff ↔ (prev_sum != curr_sum) via |delta|
                        n_sess = len(sessions_teach)
                        delta = model.NewIntVar(-n_sess, n_sess, f"delta_{teach}_{d}_{s}")
                        abs_delta = model.NewIntVar(0, n_sess, f"abs_delta_{teach}_{d}_{s}")
                        model.Add(delta == sum(prev_occ) - sum(curr_occ))
                        model.AddAbsEquality(abs_delta, delta)
                        model.Add(abs_delta >= 1).OnlyEnforceIf(diff)
                        model.Add(abs_delta == 0).OnlyEnforceIf(diff.Not())

                        transitions.append(diff)

                    penalties.append(self.weight * sum(transitions))
        else:   # On pénalise si il n'y a qu'un slot de libre dans les lunch_slots
            target = len(self.lunch_slots) - 1

            for teach in teachers:
                sessions_teach = [(c, i) for c in courses_by_teacher[teach] for i in range(c.slots_per_week)]

                for d in range(nb_days):
                    lunch_times = [d * self.nb_slots_per_day + s for s in self.lunch_slots]

                    indicators = []

                    for c, i in sessions_teach:
                        b = model.NewBoolVar(f"ll_count_{c.id}_{i}_{d}")

                        # b = 1 ⇔ session est dans lunch
                        model.AddAllowedAssignments([time[(c.id, i)]], [[t] for t in lunch_times]).OnlyEnforceIf(b)
                        model.AddForbiddenAssignments([time[(c.id, i)]], [[t] for t in lunch_times]).OnlyEnforceIf(b.Not())

                        indicators.append(b)

                    is_bad = model.NewBoolVar(f"long_lunch_{teach}_day{d}")

                    # Même encodage que LongLunch : is_bad ↔ (nb == target) via |delta|
                    n_sess = len(sessions_teach)
                    delta_nb = model.NewIntVar(-n_sess, n_sess, f"delta_nb_{teach}_{d}")
                    abs_nb = model.NewIntVar(0, n_sess, f"abs_nb_{teach}_{d}")
                    model.Add(delta_nb == sum(indicators) - target)
                    model.AddAbsEquality(abs_nb, delta_nb)
                    model.Add(abs_nb == 0).OnlyEnforceIf(is_bad)
                    model.Add(abs_nb >= 1).OnlyEnforceIf(is_bad.Not())

                    penalties.append(self.weight * is_bad)

        return penalties
    

@register
class NoGapTeacher(Constraint):

    def __init__(self, is_hard=False, is_active=True, weight=3, lunch_slots=None, nb_slots_per_day=10):
        super().__init__(is_hard=is_hard, is_active=is_active, weight=weight, lunch_slots=lunch_slots, nb_slots_per_day=nb_slots_per_day)

    def apply(self, model, slot, time, var_room, courses, groups, teachers, courses_by_group, courses_by_teacher, rooms, nb_days, nb_slots_per_day, buildings=None):
        penalties = []

        for teach in teachers:
            sessions_teach = [(c, i) for c in courses_by_teacher[teach] for i in range(c.slots_per_week)]

            for d in range(nb_days):
                # Même logique que NoGap étudiant : variables d'occupation agrégées par slot,
                # créées une seule fois et réutilisées pour tous les gaps du jour
                occ = {}
                for s in range(self.nb_slots_per_day):
                    t_abs = d * self.nb_slots_per_day + s
                    at_s = []
                    for c, i in sessions_teach:
                        bv = model.NewBoolVar(f"at_{teach}_{d}_{s}_{c.id}_{i}")
                        model.Add(time[(c.id, i)] == t_abs).OnlyEnforceIf(bv)
                        model.Add(time[(c.id, i)] != t_abs).OnlyEnforceIf(bv.Not())
                        at_s.append(bv)
                    occ_s = model.NewBoolVar(f"occ_{teach}_{d}_{s}")
                    model.Add(sum(at_s) >= 1).OnlyEnforceIf(occ_s)
                    model.Add(sum(at_s) == 0).OnlyEnforceIf(occ_s.Not())
                    occ[s] = occ_s

                for s in range(1, self.nb_slots_per_day - 1):
                    if s - 1 in self.lunch_slots or s in self.lunch_slots or s + 1 in self.lunch_slots:
                        continue

                    gap = model.NewBoolVar(f"gap_{teach}_{d}_{s}")
                    model.AddBoolAnd([occ[s - 1], occ[s].Not(), occ[s + 1]]).OnlyEnforceIf(gap)
                    model.AddBoolOr([occ[s - 1].Not(), occ[s], occ[s + 1].Not()]).OnlyEnforceIf(gap.Not())

                    penalties.append(self.weight * gap)

        return penalties
    


@register
class NoLateDayTeacher(Constraint):  # Pour moi pas nécessaire car on implémentera une contrainte Unavailable donc ca pourrait etre redondant
    def __init__(self, is_hard=False, is_active=True, weight=3, lunch_slots=None, nb_slots_per_day=10):
        super().__init__(is_hard=is_hard, is_active=is_active, weight=weight, lunch_slots=lunch_slots, nb_slots_per_day=nb_slots_per_day)

    def apply(self, model, slot, time, var_room, courses, groups, teachers, courses_by_group, courses_by_teacher, rooms, nb_days, nb_slots_per_day, buildings=None):
        penalties = []

        for teach in teachers:
            for d in range(nb_days):
                last_slots = [self.nb_slots_per_day-2, self.nb_slots_per_day-1]

                for s in last_slots:
                    t = d * self.nb_slots_per_day + s

                    for c in courses_by_teacher[teach]:
                        for i in range(c.slots_per_week):
                            b = model.NewBoolVar(f"late_{c.id}_{i}_{d}_{s}")

                            model.Add(time[(c.id, i)] == t).OnlyEnforceIf(b)
                            model.Add(time[(c.id, i)] != t).OnlyEnforceIf(b.Not())

                            penalties.append(self.weight * b)

        return penalties
    

@register
class CloserTeacher(Constraint):
    def __init__(self, is_hard=False, is_active=True, weight=3, lunch_slots=None, nb_slots_per_day=10, threshold=5):
        super().__init__(is_hard=is_hard, is_active=is_active, weight=weight, lunch_slots=lunch_slots, nb_slots_per_day=nb_slots_per_day)
        self.threshold = threshold

    def apply(self, model, slot, time, var_room, courses, groups, teachers, courses_by_group, courses_by_teacher, rooms, nb_days, nb_slots_per_day, buildings=None):
        if not buildings:
            return []

        nb_r   = len(rooms)
        nb_bat = len(buildings)
        bat_by_id  = {b.id: b   for b in buildings}
        bat_index  = {b.id: idx for idx, b in enumerate(buildings)}

        room_to_bat = [bat_index[rooms[r].bat] for r in range(nb_r)]

        exceeds_bat_flat = [
            1 if bat_by_id[buildings[b1].id].dist.get(buildings[b2].id, 0) > self.threshold else 0
            for b1 in range(nb_bat) for b2 in range(nb_bat)
        ]

        bat_var = {}
        for c in courses:
            for i in range(c.slots_per_week):
                bv = model.NewIntVar(0, nb_bat - 1, f"cTbat_{c.id}_{i}")
                model.AddElement(var_room[(c.id, i)], room_to_bat, bv)
                bat_var[(c.id, i)] = bv

        at_cache = {}

        def is_at(c_id, i, t_abs):
            key = (c_id, i, t_abs)
            if key not in at_cache:
                b = model.NewBoolVar(f"cTat_{c_id}_{i}_{t_abs}")
                model.Add(time[(c_id, i)] == t_abs).OnlyEnforceIf(b)
                model.Add(time[(c_id, i)] != t_abs).OnlyEnforceIf(b.Not())
                at_cache[key] = b
            return at_cache[key]

        penalties = []
        for teach in teachers:
            sessions_teach = [(c, i) for c in courses_by_teacher[teach]
                              for i in range(c.slots_per_week)]

            # Pré-filtrage : skip les profs dont tous les cours sont dans le même bâtiment
            possible_bats_t = {
                bat_index[r.bat]
                for c in courses_by_teacher[teach]
                for r in rooms
                if any(rt in r.room_types for rt in c.room_types)
            }
            if not any(
                exceeds_bat_flat[b1 * nb_bat + b2]
                for b1 in possible_bats_t for b2 in possible_bats_t
            ):
                continue

            for d in range(nb_days):
                bat_at = {}
                occ    = {}
                for s in range(nb_slots_per_day):
                    t_abs  = d * nb_slots_per_day + s
                    bat_s  = model.NewIntVar(0, nb_bat - 1, f"cTbat_at_{teach}_{d}_{s}")
                    bat_at[s] = bat_s
                    at_s = []
                    for c, i in sessions_teach:
                        b_at = is_at(c.id, i, t_abs)
                        model.Add(bat_s == bat_var[(c.id, i)]).OnlyEnforceIf(b_at)
                        at_s.append(b_at)
                    occ_s = model.NewBoolVar(f"cTocc_{teach}_{d}_{s}")
                    model.Add(sum(at_s) >= 1).OnlyEnforceIf(occ_s)
                    model.Add(sum(at_s) == 0).OnlyEnforceIf(occ_s.Not())
                    occ[s] = occ_s

                for s in range(nb_slots_per_day - 1):
                    comb_bat = model.NewIntVar(0, nb_bat * nb_bat - 1, f"cTcomb_{teach}_{d}_{s}")
                    model.Add(comb_bat == bat_at[s] * nb_bat + bat_at[s + 1])
                    b_thr = model.NewBoolVar(f"cTbthr_{teach}_{d}_{s}")
                    model.AddElement(comb_bat, exceeds_bat_flat, b_thr)

                    b_pen = model.NewBoolVar(f"cTpen_{teach}_{d}_{s}")
                    model.AddBoolAnd([occ[s], occ[s + 1], b_thr]).OnlyEnforceIf(b_pen)
                    model.AddBoolOr([occ[s].Not(), occ[s + 1].Not(), b_thr.Not()]).OnlyEnforceIf(b_pen.Not())
                    penalties.append(self.weight * b_pen)

        return penalties




