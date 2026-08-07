from basics import *
from gestion import *
from extractor import *
from scenarios import *
from solver import full_solve, collect_absent_intervals
from scorers import make_default_scorers, evaluate_perturbation, compute_hours, remaining_hours, check_deadline_violations
from scorers import (score_same_day, score_no_late_group, score_no_late_teacher,
                     score_no_gap_group, score_preferred_building)

# ---------------------------------------------------------------------------
# Configuration des soft scorers
# Modifier les poids ou commenter/supprimer des lignes pour personnaliser.
# Les scorers "closer_*" sont des factories : ils ont besoin de buildings_list
# et du planning courant — ils sont construits dynamiquement dans la boucle.
# Les scorers statiques (ci-dessous) sont définis une fois pour toutes.
# ---------------------------------------------------------------------------
STATIC_SCORERS = [
    # (nom,              fonction,              poids)
    ("same_day",           score_same_day,           2.0),
    ("no_late_group",      score_no_late_group,      1.0),
    ("no_late_teacher",    score_no_late_teacher,    1.0),
    ("no_gap_group",       score_no_gap_group,       0.5),
    ("preferred_building", score_preferred_building, 30.0),
]
# Poids des scorers "closer" (factories). Mettre à 0.0 pour désactiver.
CLOSER_GROUP_WEIGHT   = 0.4
CLOSER_TEACHER_WEIGHT = 0.3


# ---------------------------------------------------------------------------
# Création des variables globales pour la résolution faite dans extractor.py
# ---------------------------------------------------------------------------

edt, courses_list, rooms_list, teachers_list, buildings_list, groups_list, nb_days, deadline_days, LUNCH_DEBUT_MIN, LUNCH_FIN_MIN = extraction(filepath="Data/edt_semestre.csv", affichage_html=False)
# affichage_html_heures(edt, courses_list, teachers_list, filename="heures_base_semestre.html")  # rapport initial dans edt/

rooms_map = {r.name: r for r in rooms_list}
teachers_map = {t.id: t for t in teachers_list}
groups_map = {g.id: g for g in groups_list}
courses_map = {c.name: c for c in courses_list}


# ---------------------------------------------------------------------------
# Helpers saisie
# ---------------------------------------------------------------------------

def _parse_slots(prompt):
    """
    Saisie : 'jour,heure_debut,heure_fin' séparés par espaces
    Exemple : '0,09h30,11h00 1,14h00,15h30'
    Retourne : [(day, heure_debut, heure_fin), ...] ou None si vide.
    Redemande en cas de format invalide.
    """
    while True:
        raw = input(prompt).strip()
        if not raw:
            return None
        result = []
        ok = True
        for token in raw.split():
            parts = token.split(",")
            if len(parts) != 3:
                print(f"  Format invalide : '{token}' — attendu jour,heure_debut,heure_fin (ex: 0,09h30,11h00)")
                ok = False
                break
            try:
                day = int(parts[0])
            except ValueError:
                print(f"  Jour invalide : '{parts[0]}' — doit être un entier (0=lundi, 1=mardi...)")
                ok = False
                break
            result.append((day, parts[1].strip(), parts[2].strip()))
        if ok:
            return result


def _item_has_group(item, grp_id: str) -> bool:
    """True si grp_id est dans item.group (direct ou via subgroup_ids)."""
    for g in item.group:
        if g.id == grp_id:
            return True
        if g.subgroup_ids and grp_id in g.subgroup_ids:
            return True
    return False

def _item_has_group_broad(item, grp_id):
    if not grp_id:           # vide = on ne filtre pas, on prend tous les groupes
        return True
    parent = next((g for g in groups_list if g.id == grp_id), None) # Cherche le groupe qui a le bon id parmi groups_list
    parent_subs = set(parent.subgroup_ids) if parent and parent.subgroup_ids else set() # Crée un set des sous groupes
    for g in item.group:
        if g.id == grp_id:  # Groupe exact
            return True
        if g.id in parent_subs:  # Sous groupe du groupe demandé par l'utilisateur
            return True
    return False


def _collect_perturbation():
    """
    Demande à l'utilisateur de saisir une perturbation.
    Retourne un dict décrivant la perturbation, ou None si l'utilisateur tape 0.
    """
    print("\nType de perturbation :")
    print("  [1] Prof absent             (cours replanifiés à un autre créneau)")
    print("  [2] Salle indisponible      (cours replanifiés dans une autre salle)")
    print("  [3] Dégager un créneau      (cours déplacés hors du créneau)")
    print("  [4] Remplacement            (cours maintenus, prof remplacé)")
    print("  [5] Déplacement             (déplacer un cours précis à un autre créneau)")
    print("  [6] Permutation             (échanger deux cours de créneau)")
    print("  [7] Changement de salle     (changer la salle d'un cours)")
    print("  [8] Ajout d'une session     (ajouter une session à un cours existant)")
    print("  [9] Suppression de session  (supprimer une ou plusieurs sessions d'un cours existant)")
    print("  [0] Terminer la saisie → résoudre")
    choice = input(">>> Choix : > ").strip()

    if choice == "0":
        return None

    if choice == "1":
        tid = input(">>> ID du prof absent (ex: T_Tom) : > ").strip()
        slots = _parse_slots(
            ">>> Absences 'jour,heure_debut,heure_fin' séparées par espaces (vide = pas absent du tout) \n"
            "    ex: '0,09h30,11h00 1,14h00,15h30'\n>>> ")
        return {"type": 1, "teacher_id": tid, "intervals": slots or []}

    if choice == "2":
        rname = input(">>> Nom de la salle indisponible (ex: GB42) : > ").strip()
        slots = _parse_slots(
            ">>> Créneaux bloqués 'jour,heure_debut,heure_fin' (vide = salle retirée définitivement)\n"
            "    ex: '0,09h30,11h00'\n>>> ")
        return {"type": 2, "room": rname, "intervals": slots}

    if choice == "3":
        raw_groups = input(
            ">>> Groupes concernés séparés par espaces (vide = tous) : > ").strip()
        target_groups = raw_groups.split() if raw_groups else None
        slots = _parse_slots(
            ">>> Créneaux à libérer 'jour,heure_debut,heure_fin' séparés par espaces\n"
            "    ex: '2,14h00,15h30 3,09h30,11h00'\n>>> ")
        if not slots:
            print("Aucun créneau saisi, perturbation ignorée.")
            return {}   # sentinelle vide → re-demander
        return {"type": 3, "groups": target_groups, "intervals": slots}

    if choice == "4":
        # --- Prof concerné (optionnel si on cible un cours précis) ---
        tid_raw = input(
            ">>> ID du prof absent (ex: T_Tom) ou vide si cours sans prof : > ").strip()
        tid = tid_raw or None

        # --- Cours (optionnel, par nom) ---
        cname_raw = input(
            ">>> Nom du cours à couvrir (ex: Mat2) ou vide pour tous les cours du prof : > "
        ).strip()
        course_ids = None
        if cname_raw:
            # Collecter TOUS les ids pour ce nom (un par groupe)
            matches = [c for c in courses_list if c.name.lower() == cname_raw.lower()]
            if not matches:
                names = sorted({c.name for c in courses_list})
                print(f"  Cours '{cname_raw}' introuvable. Cours disponibles : {names}")
                return {}
            course_ids = [c.id for c in matches]

        # --- Groupes (optionnel) ---
        grp_raw = input(
            ">>> Groupes concernés séparés par espaces (vide = tous) : > ").strip()
        target_groups = grp_raw.split() if grp_raw else None

        # --- Type de séance (optionnel) ---
        stype_raw = input(
            ">>> Type de séance (TD / CM / TP) ou vide pour tous : > ").strip().upper()
        target_session_type = stype_raw if stype_raw else None

        # --- Créneaux (optionnel) ---
        slots = _parse_slots(
            ">>> Créneaux concernés 'jour,heure_debut,heure_fin' (vide = tout le semestre)\n"
            "    ex: '0,09h30,11h00'\n>>> ")

        if not tid and course_ids is None:
            print("  Il faut au moins un prof ou un cours cible.")
            return {}

        return {
            "type":                4,
            "teacher_id":          tid,
            "course_name":         cname_raw or None,
            "course_ids":          course_ids,
            "target_groups":       target_groups,
            "target_session_type": target_session_type,
            "intervals":           slots,
        }

    if choice == "5":
        # --- Cours à déplacer ---
        cname_raw = input(">>> Nom du cours à déplacer (ex: Sport) : > ").strip()
        matches = [c for c in courses_list if c.name.lower() == cname_raw.lower()]
        if not matches:
            names = sorted({c.name for c in courses_list})
            print(f"  Cours '{cname_raw}' introuvable. Cours disponibles : {names}")
            return {}

        # --- Groupe ---
        grp_raw = input(">>> Groupe du cours (ex: 1_G) : > ").strip()

        # Recherche du ScheduleItem correspondant
        matched_ids = {c.id for c in matches}
        candidates_items = sorted(
            [it for it in edt if it.course in matched_ids and _item_has_group(it, grp_raw)],
            key=lambda it: (it.day, hm(it.heure_debut)),
        )
        if not candidates_items:
            existing = [it for it in edt if it.course in matched_ids]
            print(f"  Aucun cours '{cname_raw}' pour le groupe '{grp_raw}' dans le planning.")
            if existing:
                print("  Cours trouvés pour ce nom :")
                for it in existing:
                    print(f"    {it.course} | {[g.id for g in it.group]} | {fmt_abs_day(it.day)} {it.heure_debut}–{it.heure_fin} | {it.room}")
            return {}

        # Disambiguation si plusieurs séances
        if len(candidates_items) == 1:
            to_move = candidates_items[0]
        else:
            print(f"  Plusieurs séances trouvées pour '{cname_raw}' / '{grp_raw}' :")
            for i, it in enumerate(candidates_items):
                print(f"    [{i+1}] {fmt_abs_day(it.day)} {it.heure_debut}–{it.heure_fin} salle {it.room}")
            idx_raw = input(">>> Numéro de la séance à déplacer : > ").strip()
            if not idx_raw.isdigit() or not (1 <= int(idx_raw) <= len(candidates_items)):
                print("  Choix invalide.")
                return {}
            to_move = candidates_items[int(idx_raw) - 1]

        # --- Jour cible ---
        day_raw = input(f">>> Jour cible (entier absolu, ex: 0=S1 Lun, 4=S1 Ven, 5=S2 Lun … {nb_days-1} = dernier jour) : > ").strip()
        if not day_raw.isdigit() or not (0 <= int(day_raw) < nb_days):
            print("  Jour invalide.")
            return {}
        target_day = int(day_raw)

        # --- Créneau précis (optionnel) ---
        slot_raw = input(
            ">>> Créneau précis 'heure_debut' (ex: 09h30) ou vide pour chercher automatiquement : > "
        ).strip()
        target_hd = None
        if slot_raw:
            parts = slot_raw.split(",")
            if len(parts) == 1:
                target_hd = parts[0].strip()
            else:
                print("  Format invalide pour le créneau, cherche automatiquement.")

        return {
            "type":       5,
            "to_move":    to_move,
            "target_day": target_day,
            "heure_debut": target_hd,
        }

    if choice == "6":
        def _pick_session(label):
            cname_raw = input(f">>> Nom du cours {label} (ex: Sport) : > ").strip()
            matches = [c for c in courses_list if c.name.lower() == cname_raw.lower()]
            if not matches:
                names = sorted({c.name for c in courses_list})
                print(f"  Cours '{cname_raw}' introuvable. Cours disponibles : {names}")
                return None
            grp_raw = input(f">>> Groupe du cours {label} (ex: 1_G) : > ").strip()
            matched_ids = {c.id for c in matches}
            cands = sorted(
                [it for it in edt if it.course in matched_ids and _item_has_group(it, grp_raw)],
                key=lambda it: (it.day, hm(it.heure_debut)),
            )
            if not cands:
                print(f"  Aucun cours '{cname_raw}' pour le groupe '{grp_raw}' dans le planning.")
                return None
            if len(cands) == 1:
                return cands[0]
            print(f"  Plusieurs séances trouvées pour '{cname_raw}' / '{grp_raw}' :")
            for i, it in enumerate(cands):
                print(f"    [{i+1}] {fmt_abs_day(it.day)} {it.heure_debut}–{it.heure_fin} salle {it.room}")
            idx_raw = input(f">>> Numéro de la séance {label} : > ").strip()
            if not idx_raw.isdigit() or not (1 <= int(idx_raw) <= len(cands)):
                print("  Choix invalide.")
                return None
            return cands[int(idx_raw) - 1]

        perm1 = _pick_session("1")
        if perm1 is None:
            return {}
        perm2 = _pick_session("2")
        if perm2 is None:
            return {}
        if perm1 == perm2:
            print("  Les deux cours sont identiques, permutation impossible.")
            return {}

        kr_raw = input(">>> Garder les salles d'origine ? (Y/N, défaut=N) : > ").strip().lower()
        keep_room = kr_raw in ("y", "yes")

        mc_raw = input(">>> Fallback move si échange impossible ? (Y/N, défaut=Y) : > ").strip().lower()
        move_courses = mc_raw not in ("n", "no")

        return {
            "type":         6,
            "perm1":        perm1,
            "perm2":        perm2,
            "keep_room":    keep_room,
            "move_courses": move_courses,
        }

    if choice == "7":
        # --- Cours à déplacer ---
        cname_raw = input(">>> Nom du cours dont on veut changer la salle (ex: Sport) : > ").strip()
        matches = [c for c in courses_list if c.name.lower() == cname_raw.lower()]
        if not matches:
            names = sorted({c.name for c in courses_list})
            print(f"  Cours '{cname_raw}' introuvable. Cours disponibles : {names}")
            return {}
        
        # --- Groupe ---
        grp_raw = input(">>> Groupe du cours (ex: 1_G) : > ").strip()
    
        # Recherche du ScheduleItem correspondant
        matched_ids = {c.id for c in matches}
        candidates_items = sorted(
            [it for it in edt if it.course in matched_ids and _item_has_group(it, grp_raw)],
            key=lambda it: (it.day, hm(it.heure_debut)),
        )
        if not candidates_items:
            existing = [it for it in edt if it.course in matched_ids]
            print(f"  Aucun cours '{cname_raw}' pour le groupe '{grp_raw}' dans le planning.")
            if existing:
                print("  Cours trouvés pour ce nom :")
                for it in existing:
                    print(f"    {it.course} | {[g.id for g in it.group]} | {fmt_abs_day(it.day)} {it.heure_debut}–{it.heure_fin} | {it.room}")
                return {}

        # Disambiguation si plusieurs séances
        if len(candidates_items) == 1:
            to_move = candidates_items[0]
        else:
            print(f"  Plusieurs séances trouvées pour '{cname_raw}' / '{grp_raw}' :")
            for i, it in enumerate(candidates_items):
                print(f"    [{i+1}] {fmt_abs_day(it.day)} {it.heure_debut}–{it.heure_fin} salle {it.room}")
            idx_raw = input(">>> Numéro de la séance à déplacer : > ").strip()
            if not idx_raw.isdigit() or not (1 <= int(idx_raw) <= len(candidates_items)):
                print("  Choix invalide.")
                return {}
            to_move = candidates_items[int(idx_raw) - 1]

        # --- Salle précise (optionnel) ---
        room_raw = input(
            ">>> Salle précise (ex: GP1) ou vide pour chercher automatiquement : > "
        ).strip()

        if room_raw:
            br_raw   = input(">>> Si cette salle est indisponible, chercher la meilleure alternative ? (Y/N, défaut=Y) : > ").strip().lower()
            best_room = br_raw not in ("n", "no")
            tup = (to_move, room_raw, best_room)
        else:
            tup = (to_move,)

        return {
            "type":      7,
            "to_change": [tup],
        }
    
    if choice == "8":
            # --- Cours à déplacer ---
            cname_raw = input(">>> Nom du cours pour lequel on veut rajouter une session (ex: Electro) : > ").strip()
            matches = [c for c in courses_list if c.name.lower() == cname_raw.lower()]
            if not matches:
                names = sorted({c.name for c in courses_list})
                print(f"  Cours '{cname_raw}' introuvable. Cours disponibles : {names}")
                return {}
            else:
                course = courses_map[cname_raw]
            
            # --- Group ---
            grp_raw = input(">>> Groupe du cours (ex: 1_G) : > ").strip()
            matches = [grp_raw for g in groups_list if g.id.lower() == grp_raw.lower()]
            if not matches:
                names = sorted({g.id for g in groups_list})
                print(f"  Groupe '{grp_raw}' introuvable. Groupes disponibles : {names}")
                return {}
            else:
                group = groups_map[grp_raw]

            # --- Teacher ---
            teach_raw = input(">>> Professeur du cours (ex: T_Tom) : > ").strip()
            matches = [teach_raw for t in teachers_list if t.id.lower() == teach_raw.lower()]
            if not matches:
                names = sorted({t.id for t in teachers_list})
                print(f"  Prof '{teach_raw}' introuvable. Profs disponibles : {names}")
                return {}
            else:
                teacher = teachers_map[teach_raw]

            # --- Session_type ---
            session_type = input(">>> Type de session du cours (ex: TD) : > ")

            # --- Durée ---
            duration = int(input(">>> Durée de la session en minutes (ex: 1h15 = 75min) : > ").strip())
    
            # --- Semaine précise (optionnel) ---
            week = input(">>> Semaine précise (0=semaine 1, 1=semaine2, ...) ou vide pour chercher automatiquement : > ").strip()

            if week:
                week = int(week)
                # --- Jour précis (optionnel) ---
                day = input(">>> Jour précis de la semaine ou vide pour chercher automatiquement : > ").strip()

                if day:
                    day=int(day)
                    hd = input(">>> Heure de début du cours précise ou vide pour chercher automatiquement : > ").strip()
                    if not hd:
                        hd=None
                else:
                    hd=None
            else:
                week=None
                day=None
                hd=None

            # --- Salle précise (optionnel) ---
            room_raw = input(">>> Salle souhiatée (ex: GB42) ou vide pour chercher automatiquement: > ").strip()
            if room_raw:
                room = rooms_map[room_raw]
            else:
                room=None

            tup = (course, teacher, group, session_type, duration, week, day, room, hd)

            return {
                "type":   8,
                "to_add": [tup],
            }

    if choice == "9":
        # --- Session à supprimer ---
        cname_raw = input(">>> Nom du cours dont on veut supprimer une session (ex: Sport) : > ").strip()
        matches = [c for c in courses_list if c.name.lower() == cname_raw.lower()]
        if not matches:
            names = sorted({c.name for c in courses_list})
            print(f"  Cours '{cname_raw}' introuvable. Cours disponibles : {names}")
            return {}
        
        # --- Groupe ---
        grp_raw = input(">>> Groupe du cours (ex: 1_G) : > ").strip()

        # --- OPTIONNEL : Type de session ---
        session_type = input(">>> Type de la session (ex: TD, vide = tous types) > ").strip() or None

        # --- OPTIONNEL : Semaine ---
        week_raw = input("ATTENTION : toute demande de suppression de sessions déjà passées ne sera pas prise en compte\n>>> Semaine de la session voulue (vide pour toutes les semaines) > ").strip()

        matched_ids = {c.id for c in matches}

        def _stype_ok(it):
            return session_type is None or session_type in it.session_type

        if week_raw != "":
            week = int(week_raw)
            # --- OPTIONNEL : Jour ---
            day_raw = input(">>> Jour de la semaine de la session à supprimer (vide pour tous les jours) > ").strip()

            if day_raw != "":
                day = int(day_raw)
                day_abs = to_abs_day(week, day)
                # --- OPTIONNEL : Heure_debut ---
                hd = input(">>> Heure de début de la session à supprimer (vide pour toutes celles du jour) > ").strip()

                if hd != "":
                    candidates_items = sorted(
                        [it for it in edt if it.course in matched_ids and _item_has_group_broad(it, grp_raw)
                         and _stype_ok(it) and it.day == day_abs and hd in it.heure_debut],
                        key=lambda it: (it.day, hm(it.heure_debut)),
                    )
                else:
                    candidates_items = sorted(
                        [it for it in edt if it.course in matched_ids and _item_has_group_broad(it, grp_raw)
                         and _stype_ok(it) and it.day == day_abs],
                        key=lambda it: (it.day, hm(it.heure_debut)),
                    )
            else:
                days_range = [to_abs_day(week, i) for i in range(5)]
                candidates_items = sorted(
                    [it for it in edt if it.course in matched_ids and _item_has_group_broad(it, grp_raw)
                     and _stype_ok(it) and it.day in days_range],
                    key=lambda it: (it.day, hm(it.heure_debut)),
                )
        else:
            candidates_items = sorted(
                [it for it in edt if it.course in matched_ids and _item_has_group_broad(it, grp_raw)
                 and _stype_ok(it)],
                key=lambda it: (it.day, hm(it.heure_debut)),
            )

        if not candidates_items:
            existing = [it for it in edt if it.course in matched_ids]
            grp_info = f" pour le groupe '{grp_raw}'" if grp_raw else ""
            stype_info = f" (type {session_type})" if session_type else ""
            print(f"  Aucun cours '{cname_raw}'{grp_info}{stype_info} dans le planning.")
            if existing:
                print("  Sessions trouvées pour ce nom :")
                for it in existing:
                    print(f"    {[g.id for g in it.group]} | {fmt_abs_day(it.day)} {it.heure_debut}–{it.heure_fin} | {it.session_type} | {it.room}")
            return {}


        return {
            "type":      9,
            "to_remove": candidates_items,
        }
    
    print("Choix invalide, ignoré.")
    return {}  # sentinelle vide → re-demander


# ---------------------------------------------------------------------------
# Jour courant (borne inférieure pour le replacement : on ne replace pas dans le passé)
# ---------------------------------------------------------------------------
_current_day_raw = input("Jour courant (absolu, ex: 12 = S3J2, 0 = début du semestre) [défaut=-1] : > ").strip()
try:
    CURRENT_DAY = int(_current_day_raw) if _current_day_raw else -1
except ValueError:
    CURRENT_DAY = 0
    print("  Valeur invalide, CURRENT_DAY = 0.")
print(f"  Jour courant : {CURRENT_DAY} (les cours ne peuvent être replacés qu'à partir du jour {CURRENT_DAY + 1})")

import basics; basics.MIN_DAY = CURRENT_DAY +1

# ---------------------------------------------------------------------------
# Collecte de toutes les perturbations
# ---------------------------------------------------------------------------

perturbations = []
print("\n=== Saisie des perturbations (0 pour résoudre) ===")
while True:
    p = _collect_perturbation()
    if p is None:           # utilisateur a tapé 0, aucune perturbation
        break
    if p:                   # dict non vide = perturbation valide
        perturbations.append(p)
        print(f"  Perturbation {len(perturbations)} enregistrée.")

if not perturbations:
    print("Aucune perturbation saisie, fin du programme.")
else:
    # -----------------------------------------------------------------------
    # Choix du mode de résolution
    # -----------------------------------------------------------------------
    print("\nMode de résolution :")
    print("  [1] Cascade   — une perturbation à la fois, résultat de chacune sert d'entrée à la suivante")
    print("  [2] Global    — toutes les perturbations collectées en une seule passe CP-SAT (full_solve)")
    mode_choice = input(">>> Choix [1/2, défaut=1] : > ").strip()
    use_full_solve = (mode_choice == "2")

    if use_full_solve:
        print(f"\n=== Résolution de {len(perturbations)} perturbation(s) en une passe globale (full_solve) ===")
    else:
        print(f"\n=== Résolution de {len(perturbations)} perturbation(s) en cascade ===")

    _run_ts   = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    _run_uid  = uuid.uuid4().hex[:6]
    _run_id   = f"{_run_ts}_{_run_uid}"
    _run_dir  = os.path.join(EDT_DIR, _run_id)
    os.makedirs(_run_dir, exist_ok=True)

    current_schedule    = edt
    all_truly_cancelled = []   # cours absents de l'EDT (type 1/2/3)
    all_put_back        = []   # cours remis en place (types 5/6/7, demande non applicable)
    all_rescheduled     = []   # cours effectivement replacés avec leur nouvelle position
    all_originals       = []   # positions originales des cours replacés (même ordre que all_rescheduled pour types 1-3)
    all_added           = []   # nouvelles sessions ajoutées avec succès (type 8)
    all_not_added       = []   # nouvelles sessions non placées (type 8)
    all_removed         = []   # sessions supprimées (type 9)
    all_not_removed     = []   # sessions non supprimées (type 9)
    total_attempted   = 0
    solver_statuses   = []
    room_unavail      = {}
    teacher_unavail   = defaultdict(list)
    group_unavail     = defaultdict(list)
    _t_start          = datetime.datetime.now()

    if use_full_solve:
        named_scorers = make_default_scorers(buildings_list, edt,
                                  deadline_days=deadline_days or None,
                                  static_scorers=STATIC_SCORERS,
                                  closer_group_weight=CLOSER_GROUP_WEIGHT,
                                  closer_teacher_weight=CLOSER_TEACHER_WEIGHT)
        scorers = [(fn, w) for _, fn, w in named_scorers]
        valid_starts = sorted(set(hm(item.heure_debut) for item in edt))

        current_schedule, all_truly_cancelled, all_put_back, total_attempted, sstatus, all_rescheduled, _fs_added, _fs_not_added, _fs_removed, _fs_not_removed, _fs_originals = full_solve(
            schedule=edt,
            list_perturb=perturbations,
            courses=courses_list,
            rooms=rooms_list,
            teachers=teachers_list,
            groups=groups_list,
            valid_starts=valid_starts,
            lunch_debut_min=LUNCH_DEBUT_MIN,
            lunch_fin_min=LUNCH_FIN_MIN,
            soft_scorers=scorers,
            teacher_replacement_fn=teacher_replacement,
            move_fn=move_one,
            move_all_fn=move_all,
            permutation_fn=permutation,
            room_change_fn=all_room_change,
            add_session_fn=add_sessions,
            remove_session_fn=remove_sessions,
            min_day=CURRENT_DAY + 1,
            nb_days=nb_days,
        )
        # sstatus est maintenant un dict phase_statuses
        solver_statuses = list(sstatus.values())  # pour log_perturbation (liste plate de statuts)
        all_added.extend(_fs_added)
        all_not_added.extend(_fs_not_added)
        all_removed.extend(_fs_removed)
        all_not_removed.extend(_fs_not_removed)
        # Pour full_solve, les originals sont dans info_perturb["affected"] —
        # on les reconstruit ici à partir de edt en identifiant les items absents.
        all_originals.extend(_fs_originals)

        # Construire room_unavail / teacher_unavail / group_unavail pour le HTML
        for p in perturbations:
            if p["type"] == 1:
                for iv in p["intervals"]:
                    teacher_unavail[p["teacher_id"]].append(iv)
            elif p["type"] == 2:
                room_unavail[p["room"]] = p["intervals"]
            elif p["type"] == 3:
                affected_groups = p["groups"] or sorted({g.id for item in edt for g in item.group})
                for g in affected_groups:
                    for iv in p["intervals"]:
                        group_unavail[g].append(iv)

    if not use_full_solve:
        global_absent = collect_absent_intervals(perturbations, groups_list, rooms_list, nb_days)
        for i, p in enumerate(perturbations, 1):
            if p["type"]==1: typ="Prof absent"
            elif p["type"]==2: typ="Salle indispo"
            elif p["type"]==3: typ="Créneau à libérer"
            elif p["type"]==4: typ="Remplacement de prof"
            elif p["type"]==5: typ="Déplacement de session"
            elif p["type"]==6: typ="Permutation de sessions"
            elif p["type"]==7: typ="Changement de salle"
            elif p["type"]==8: typ="Ajout de session"
            elif p["type"]==9: typ="Suppression de session"
            else: typ=f"Type {p['type']}"

            print(f"\n--- Perturbation {i}/{len(perturbations)} ({typ})---")

            # Scorers reconstruits à chaque perturbation : les factories Closer
            # utilisent le planning courant pour trouver les cours voisins.
            named_scorers = make_default_scorers(buildings_list, current_schedule,
                                      static_scorers=STATIC_SCORERS,
                                      closer_group_weight=CLOSER_GROUP_WEIGHT,
                                      closer_teacher_weight=CLOSER_TEACHER_WEIGHT)
            scorers       = [(fn, w) for _, fn, w in named_scorers]  # format attendu par les scénarios

            rescheduled_this = []
            put_back_this    = []

            if p["type"] == 1:
                current_schedule, cancelled, n, sstatus, rescheduled_this, originals_this = teacher_absent(
                    current_schedule, courses_list, rooms_list, nb_days,
                    teacher_id=p["teacher_id"], absent_intervals=p["intervals"],
                    lunch_debut_min=LUNCH_DEBUT_MIN, lunch_fin_min=LUNCH_FIN_MIN, global_absent=global_absent,
                    soft_scorers=scorers, min_day=CURRENT_DAY + 1,
                )
                for iv in p["intervals"]:
                    teacher_unavail[p["teacher_id"]].append(iv)

            elif p["type"] == 2:
                current_schedule, cancelled, n, sstatus, rescheduled_this, originals_this = room_unavailable(
                    current_schedule, courses_list, rooms_list, nb_days,
                    room_name=p["room"], absent_intervals=p["intervals"],
                    lunch_debut_min=LUNCH_DEBUT_MIN, lunch_fin_min=LUNCH_FIN_MIN, global_absent=global_absent,
                    soft_scorers=scorers, min_day=CURRENT_DAY + 1,
                )
                room_unavail[p["room"]] = p["intervals"]

            elif p["type"] == 3:
                current_schedule, cancelled, n, sstatus, rescheduled_this, originals_this = free_slot(
                    current_schedule, courses_list, rooms_list, nb_days,
                    freed_intervals=p["intervals"], groups=p["groups"],
                    lunch_debut_min=LUNCH_DEBUT_MIN, lunch_fin_min=LUNCH_FIN_MIN, global_absent=global_absent,
                    soft_scorers=scorers, min_day=CURRENT_DAY + 1,
                )
                affected = p["groups"] or sorted({g.id for item in edt for g in item.group})
                for g in affected:
                    for iv in p["intervals"]:
                        group_unavail[g].append(iv)

            elif p["type"] == 4:
                originals_this           = []   # pas de déplacement de créneau
                # Remplacement : le cours garde son créneau, on change juste le prof
                schedule_pre_replacement = current_schedule
                current_schedule, cancelled, n, sstatus, alog = teacher_replacement(
                    current_schedule, courses_list, rooms_list, teachers_list, nb_days,
                    lunch_debut_min=LUNCH_DEBUT_MIN, lunch_fin_min=LUNCH_FIN_MIN,
                    global_absent=global_absent,
                    absent_teacher_id=p.get("teacher_id"),
                    target_course_ids=p.get("course_ids"),
                    target_groups=p.get("target_groups"),
                    target_session_type=p.get("target_session_type"),
                    absent_intervals=p.get("intervals"),
                )
                # Items dont le prof a changé = items reschedulés pour le remplacement
                pre_keys = {(it.course, tuple(g.id for g in it.group), it.day, it.heure_debut, it.heure_fin): it.teacher.id
                            for it in schedule_pre_replacement}
                rescheduled_this = [
                    it for it in current_schedule
                    if pre_keys.get((it.course, tuple(g.id for g in it.group), it.day, it.heure_debut, it.heure_fin))
                       != it.teacher.id
                ]
                # Log adéquation + heures des remplaçants
                if alog:
                    adequacy_avg = sum(e["adequacy"] for e in alog if e["adequacy"] is not None)
                    n_assigned   = sum(1 for e in alog if e["adequacy"] is not None)
                    if n_assigned:
                        print(f"  Adéquation moyenne des remplaçants : "
                              f"{adequacy_avg/n_assigned:.2f}")
                # Afficher les heures des profs sollicités (utilise replacement_id pour compute_hours)
                involved_tids = {e["replacement_id"] for e in alog if e.get("replacement_id")}
                if involved_tids:
                    print("  Heures des remplaçants après assignation :")
                    tmap = {t.id: t for t in teachers_list}
                    for tid in sorted(involved_tids):
                        t     = tmap.get(tid)
                        h     = compute_hours(tid, current_schedule)
                        maxh  = None
                        if t:
                            maxh = t.max_hours or (MAX_HOURS_BY_TYPE.get(t.teacher_type)
                                                   if t.teacher_type else None)
                        tname     = t.name if t else tid
                        quota_str = f" / {maxh:.0f}h quota" if maxh else ""
                        print(f"    {tname} ({tid}): {h:.2f}h total{quota_str}")

            elif p["type"] == 5:
                valid_starts_move = sorted(set(hm(item.heure_debut) for item in current_schedule))
                ####! pour pouvoir choisir le slot que l'on préfère, il faut passer get_slot à slot_picker_fn
                current_schedule, done, placed = move_one(
                    schedule=current_schedule,
                    to_move=p["to_move"],
                    lunch_debut_min=LUNCH_DEBUT_MIN,
                    lunch_fin_min=LUNCH_FIN_MIN,
                    day=p["target_day"],
                    valid_starts=valid_starts_move,
                    courses=courses_list,
                    rooms=rooms_list,
                    heure_debut=p.get("heure_debut"),
                    soft_scorers=scorers,
                    slot_picker_fn=best_slot,
                    global_absent=global_absent,
                )

                if done is None:  # Session ignorée car dans le passé
                    continue

                cancelled        = []
                put_back_this    = [] if done else [p["to_move"]]
                n                = 1
                sstatus          = "MOVED" if done else "CANCELLED"
                originals_this   = [p["to_move"]] if done else []
                rescheduled_this = [placed] if done and placed else []
                to_move      = p["to_move"]
                if done:
                    p["placed_item"] = placed
                    req_hd = p.get("heure_debut")
                    as_requested = (req_hd is None or (placed and placed.heure_debut == req_hd))
                    p["placed_as_requested"] = as_requested
                    if placed and not as_requested:
                        print(f"  ⚠  Créneau demandé : {req_hd} — créneau attribué : {placed.heure_debut} {fmt_abs_day(placed.day)} salle {placed.room} (créneau demandé indisponible)")
                else:
                    p["placed_item"] = None
                    p["placed_as_requested"] = False

            elif p["type"] == 6:
                valid_starts_perm = sorted(set(hm(item.heure_debut) for item in current_schedule))
                perm1, perm2 = p["perm1"], p["perm2"]
                c1_key = base_course_id(perm1.course)
                c2_key = base_course_id(perm2.course)
                c1_obj = next((c for c in courses_list if c.id == c1_key), None)
                c2_obj = next((c for c in courses_list if c.id == c2_key), None)
                c1_name = c1_obj.name if c1_obj else str(perm1.course)
                c2_name = c2_obj.name if c2_obj else str(perm2.course)
                print(f"  '{c1_name}' [{', '.join(g.id for g in perm1.group)}] {fmt_abs_day(perm1.day)} {perm1.heure_debut}–{perm1.heure_fin} {perm1.room}"
                      f"  ⇄  '{c2_name}' [{', '.join(g.id for g in perm2.group)}] {fmt_abs_day(perm2.day)} {perm2.heure_debut}–{perm2.heure_fin} {perm2.room}")
                current_schedule, done, placed_items = permutation(
                    schedule=current_schedule,
                    perm1=perm1, perm2=perm2,
                    lunch_debut_min=LUNCH_DEBUT_MIN,
                    lunch_fin_min=LUNCH_FIN_MIN,
                    valid_starts=valid_starts_perm,
                    courses=courses_list,
                    rooms=rooms_list,
                    soft_scorers=scorers,
                    slot_picker_fn=get_slot,
                    keep_room=p["keep_room"],
                    move_courses=p["move_courses"],
                    global_absent=global_absent,
                )

                if done is None:
                    continue

                cancelled        = []
                put_back_this    = [] if done else [perm1, perm2]
                n                = 2
                sstatus          = "PERMUTED" if done else "CANCELLED"
                originals_this   = [perm1, perm2] if done else []
                rescheduled_this = [pi for pi in (placed_items or []) if pi is not None] if done else []
                p["placed_items"] = placed_items
                if placed_items:
                    for pi in placed_items:
                        if pi is not None:
                            print(f"    → {fmt_abs_day(pi.day)} {pi.heure_debut}–{pi.heure_fin} salle {pi.room}")

            elif p["type"] == 7:
                named_scorers_7 = make_default_scorers(buildings_list, current_schedule,
                                          static_scorers=STATIC_SCORERS,
                                          closer_group_weight=CLOSER_GROUP_WEIGHT,
                                          closer_teacher_weight=CLOSER_TEACHER_WEIGHT)
                scorers_7 = [(fn, w) for _, fn, w in named_scorers_7]
                current_schedule, exact_items, moved_items, rc_status, not_done, specific_not_done = all_room_change(
                    schedule=current_schedule,
                    to_change=p["to_change"],
                    lunch_debut_min=LUNCH_DEBUT_MIN,
                    lunch_fin_min=LUNCH_FIN_MIN,
                    courses=courses_list,
                    rooms=rooms_list,
                    soft_scorers=scorers_7,
                    global_absent=global_absent,
                )
                for item in not_done + specific_not_done:
                    current_schedule.append(item)
                cancelled        = []
                put_back_this    = not_done + specific_not_done
                n                = len(p["to_change"])
                sstatus          = rc_status
                originals_this   = []
                rescheduled_this = exact_items + moved_items
                p["placed_items"] = exact_items + moved_items

            elif p["type"]==8:
                named_scorers_8 = make_default_scorers(buildings_list, current_schedule,
                                                          static_scorers=STATIC_SCORERS,
                                                          closer_group_weight=CLOSER_GROUP_WEIGHT,
                                                          closer_teacher_weight=CLOSER_TEACHER_WEIGHT)
                scorers_8 = [(fn, w) for _, fn, w in named_scorers_8]
                current_schedule, done, not_done, ss_status = add_sessions(
                                    schedule=current_schedule,
                                    to_add=p["to_add"],
                                    lunch_debut_min=LUNCH_DEBUT_MIN,
                                    lunch_fin_min=LUNCH_FIN_MIN,
                                    nb_days=nb_days,
                                    courses=courses_list,
                                    rooms=rooms_list,
                                    soft_scorers=scorers_8,
                                    global_absent=global_absent,
                                )
                all_added.extend(done)
                all_not_added.extend(not_done)
                cancelled        = []
                put_back_this    = []
                sstatus          = ss_status
                rescheduled_this = []
                originals_this   = []
                n = len(done) + len(not_done)

            elif p["type"]==9:
                current_schedule, done, not_done, ss_status = remove_sessions(
                                    schedule=current_schedule,
                                    to_remove=p["to_remove"]
                                )
                all_removed.extend(done)
                all_not_removed.extend(not_done)
                cancelled        = []
                put_back_this    = []
                sstatus          = ss_status
                rescheduled_this = []
                originals_this   = []
                n = len(done) + len(not_done)
                

            all_truly_cancelled.extend(cancelled)
            all_put_back.extend(put_back_this)
            total_attempted += n
            solver_statuses.append(sstatus)
            all_rescheduled.extend(rescheduled_this)
            all_originals.extend(originals_this)

    _duration = (datetime.datetime.now() - _t_start).total_seconds()

    # -----------------------------------------------------------------------
    # Tableau des déplacements (cours touchés → avant / après)
    # -----------------------------------------------------------------------
    _move_course_map = {c.id: c for c in courses_list}
    _move_course_map.update({str(c.id): c for c in courses_list})

    _cancelled_ids = {id(it) for it in all_truly_cancelled}
    _move_rows = []
    for orig, new_it in zip(
        (o for o in all_originals if id(o) not in _cancelled_ids),
        all_rescheduled,
    ):
        if orig is None:
            continue
        cobj  = _move_course_map.get(base_course_id(orig.course))
        cname = cobj.name if cobj else str(orig.course)
        grp   = ", ".join(g.id for g in orig.group)
        avant = f"{fmt_abs_day(orig.day)} {orig.heure_debut}–{orig.heure_fin} {orig.room}"
        apres = f"{fmt_abs_day(new_it.day)} {new_it.heure_debut}–{new_it.heure_fin} {new_it.room}"
        _move_rows.append((cname, grp, avant, apres))

    if _move_rows:
        _c1 = max(len("Cours"),  max(len(r[0]) for r in _move_rows))
        _c2 = max(len("Groupe"), max(len(r[1]) for r in _move_rows))
        _c3 = max(len("Avant"),  max(len(r[2]) for r in _move_rows))
        _c4 = max(len("Après"),  max(len(r[3]) for r in _move_rows))
        _hdr = f"  {'Cours':{_c1}} | {'Groupe':{_c2}} | {'Avant':{_c3}} | {'Après':{_c4}}"
        _sep = "  " + "-" * (_c1 + _c2 + _c3 + _c4 + 13)
        print(f"\n============= Cours déplacés ({len(_move_rows)}) =============")
        print(_hdr)
        print(_sep)
        for cname, grp, avant, apres in _move_rows:
            print(f"  {cname:{_c1}} | {grp:{_c2}} | {avant:{_c3}} | {apres:{_c4}}")

    # Table "Cours ajoutés"
    _add_rows = []
    for item in all_added:
        cobj  = _move_course_map.get(base_course_id(item.course))
        cname = cobj.name if cobj else str(item.course)
        grp   = ", ".join(g.id for g in item.group)
        slot  = f"{fmt_abs_day(item.day)} {item.heure_debut}–{item.heure_fin} {item.room}"
        _add_rows.append((cname, grp, slot))

    if _add_rows:
        _a1 = max(len("Cours"),  max(len(r[0]) for r in _add_rows))
        _a2 = max(len("Groupe"), max(len(r[1]) for r in _add_rows))
        _a3 = max(len("Créneau"), max(len(r[2]) for r in _add_rows))
        _ahdr = f"  {'Cours':{_a1}} | {'Groupe':{_a2}} | {'Créneau':{_a3}}"
        _asep = "  " + "-" * (_a1 + _a2 + _a3 + 9)
        print(f"\n============= Cours ajoutés ({len(_add_rows)}) =============")
        print(_ahdr)
        print(_asep)
        for cname, grp, slot in _add_rows:
            print(f"  {cname:{_a1}} | {grp:{_a2}} | {slot:{_a3}}")

    if all_not_added:
        print(f"\n============= Sessions non placées ({len(all_not_added)}) =============")
        for item in all_not_added:
            cobj  = _move_course_map.get(base_course_id(item.course))
            cname = cobj.name if cobj else str(item.course)
            grp   = ", ".join(g.id for g in item.group)
            req   = f"{fmt_abs_day(item.day)} {item.heure_debut}" if item.day is not None else "créneau libre"
            print(f"  ✗ {cname} [{grp}] — demandé : {req}")

    # Table "Cours supprimés"
    _rem_rows = []
    for item in all_removed:
        cobj  = _move_course_map.get(base_course_id(item.course))
        cname = cobj.name if cobj else str(item.course)
        grp   = ", ".join(g.id for g in item.group)
        slot  = f"{fmt_abs_day(item.day)} {item.heure_debut}–{item.heure_fin} {item.room}"
        _rem_rows.append((cname, grp, slot))

    if _rem_rows:
        _a1 = max(len("Cours"),  max(len(r[0]) for r in _rem_rows))
        _a2 = max(len("Groupe"), max(len(r[1]) for r in _rem_rows))
        _a3 = max(len("Créneau"), max(len(r[2]) for r in _rem_rows))
        _ahdr = f"  {'Cours':{_a1}} | {'Groupe':{_a2}} | {'Créneau':{_a3}}"
        _asep = "  " + "-" * (_a1 + _a2 + _a3 + 9)
        print(f"\n============= Sessions supprimées ({len(_rem_rows)}) =============")
        print(_ahdr)
        print(_asep)
        for cname, grp, slot in _rem_rows:
            print(f"  {cname:{_a1}} | {grp:{_a2}} | {slot:{_a3}}")

    if all_not_removed:
        print(f"\n============= Sessions non supprimées ({len(all_not_removed)}) =============")
        for item in all_not_removed:
            cobj  = _move_course_map.get(base_course_id(item.course))
            cname = cobj.name if cobj else str(item.course)
            grp   = ", ".join(g.id for g in item.group)
            print(f"  ✗ {cname} [{grp}] {fmt_abs_day(item.day)} {item.heure_debut}")

    # Sérialiser pour le log
    _rescheduled_moves = [
        {"course": r[0], "group": r[1], "avant": r[2], "apres": r[3]}
        for r in _move_rows
    ]
    _added_log = [
        {"course": r[0], "group": r[1], "slot": r[2]}
        for r in _add_rows
    ]
    _not_added_log = [
        {
            "course": (_move_course_map.get(base_course_id(it.course)) or type("", (), {"name": str(it.course)})()).name,
            "group":  [g.id for g in it.group],
            "requested_day": it.day,
            "requested_hd":  it.heure_debut,
        }
        for it in all_not_added
    ]
    _removed_log = [
            {"course": r[0], "group": r[1], "slot": r[2]}
            for r in _rem_rows
        ]
    _not_removed_log = [
        {
            "course": (_move_course_map.get(base_course_id(it.course)) or type("", (), {"name": str(it.course)})()).name,
            "group":  [g.id for g in it.group],
            "day": it.day,
            "hd":  it.heure_debut,
            "hf":  it.heure_fin,
        }
        for it in all_not_removed
    ]

    # Évaluation sur le planning COMPLET (pas seulement les cours replacés) :
    # le delta reflète l'impact réel de la perturbation sur la qualité globale de l'EDT.
    _base_scorers  = make_default_scorers(buildings_list, edt,
                                  deadline_days=deadline_days or None,
                                  static_scorers=STATIC_SCORERS,
                                  closer_group_weight=CLOSER_GROUP_WEIGHT,
                                  closer_teacher_weight=CLOSER_TEACHER_WEIGHT)
    _final_scorers = make_default_scorers(buildings_list, current_schedule,
                                  deadline_days=deadline_days or None,
                                  static_scorers=STATIC_SCORERS,
                                  closer_group_weight=CLOSER_GROUP_WEIGHT,
                                  closer_teacher_weight=CLOSER_TEACHER_WEIGHT)

    _scores_base = evaluate_perturbation(
        rescheduled=edt,
        final_schedule=edt,
        courses=courses_list,
        rooms=rooms_list,
        named_scorers=_base_scorers,
        lunch_debut_min=LUNCH_DEBUT_MIN,
        lunch_fin_min=LUNCH_FIN_MIN,
    )
    _scores_perturb = evaluate_perturbation(
        rescheduled=current_schedule,
        final_schedule=current_schedule,
        courses=courses_list,
        rooms=rooms_list,
        named_scorers=_final_scorers,
        lunch_debut_min=LUNCH_DEBUT_MIN,
        lunch_fin_min=LUNCH_FIN_MIN,
    )
    _scores_delta = {
        k: round(_scores_perturb.get(k, 0.0) - _scores_base.get(k, 0.0), 4)
        for k in _scores_perturb
    }

    print(f"\n=== Score qualité de l'emploi du temps complet ===")
    print(f"  {'scorer':20s}   {'base':>12}  {'perturb':>12}  {'delta':>12}")
    print(f"  {'-'*20}   {'------------':>12}  {'------------':>12}  {'------------':>12}")
    for k in _scores_perturb:
        b = _scores_base.get(k, 0.0)
        p = _scores_perturb[k]
        d = _scores_delta[k]
        sign = "▲" if d > 0 else ("▼" if d < 0 else " ")
        print(f"  {k:20s} : {b:12.4f}  {p:12.4f}  {sign}{abs(d):11.4f}")
    _course_map = {c.id: c for c in courses_list}
    _course_map.update({str(c.id): c for c in courses_list})

    # -----------------------------------------------------------------------
    # Vérification des deadlines
    # -----------------------------------------------------------------------
    _violations = check_deadline_violations(all_rescheduled, deadline_days or {}, DEADLINE_BUFFER_DAYS)
    if _violations:
        print(f"\n⚠  {len(_violations)} cours replanifié(s) trop tard (deadline dépassée) :")
        for item in _violations:
            cobj  = _course_map.get(base_course_id(item.course))
            cname = cobj.name if cobj else str(item.course)
            dl    = (deadline_days or {}).get(base_course_id(item.course))
            jour_place    = fmt_abs_day(item.day)
            jour_deadline = fmt_abs_day(dl - DEADLINE_BUFFER_DAYS) if dl is not None else "?"
            print(f"  - {cname} ({[g.id for g in item.group]}) placé {jour_place}, deadline {jour_deadline}")

    # -----------------------------------------------------------------------
    # Bilan global
    # -----------------------------------------------------------------------
    def _fmt_item(item):
        cobj  = _course_map.get(base_course_id(item.course))
        cname = cobj.name if cobj else str(item.course)
        jour  = fmt_abs_day(item.day)
        return f"{cname} [{', '.join(g.id for g in item.group)}] {jour} {item.heure_debut}–{item.heure_fin}"

    total_problems = len(all_truly_cancelled) + len(all_put_back) + len(all_not_added) + len(all_not_removed)
    print(f"\n=== Bilan des perturbations ===")
    if not total_problems:
        print("  Toutes les perturbations ont été appliquées avec succès.")
    if all_truly_cancelled:
        print(f"  Cours annulés — absents de l'EDT ({len(all_truly_cancelled)}) :")
        for item in all_truly_cancelled:
            print(f"    - {_fmt_item(item)}")
    if all_put_back:
        print(f"  Cours remis en place — demande non applicable ({len(all_put_back)}) :")
        for item in all_put_back:
            print(f"    - {_fmt_item(item)}")
    if all_not_added:
        print(f"  Sessions non placées — ajout impossible ({len(all_not_added)}) :")
        for item in all_not_added:
            cobj  = _course_map.get(base_course_id(item.course))
            cname = cobj.name if cobj else str(item.course)
            req   = f"{fmt_abs_day(item.day)} {item.heure_debut}" if item.day is not None else "créneau libre"
            print(f"    - {cname} [{', '.join(g.id for g in item.group)}] demandé : {req}")
    if all_not_removed:
        print(f"  Sessions non supprimées — ajout impossible ({len(all_not_removed)}) :")
        for item in all_not_removed:
            cobj  = _course_map.get(base_course_id(item.course))
            cname = cobj.name if cobj else str(item.course)
            print(f"    - {cname} [{', '.join(g.id for g in item.group)}] {fmt_abs_day(item.day)} {item.heure_debut}")


    final_name = "edt"
    save_edt(current_schedule, final_name, folder=_run_dir)
    print(f"\nEDT final sauvegardé : {_run_dir}/{final_name}.json")

    log_perturbation(
        input_edt="extracted_edt_v2",
        output_edt=f"{_run_id}/edt",
        perturbations=perturbations,
        total_attempted=total_attempted,
        cancelled=all_truly_cancelled + all_put_back,
        courses=courses_list,
        duration=_duration,
        nb_days=nb_days,
        lunch_debut_min=LUNCH_DEBUT_MIN,
        lunch_fin_min=LUNCH_FIN_MIN,
        solver_statuses=solver_statuses,
        scores_base=_scores_base,
        scores_perturb=_scores_perturb,
        scores_delta=_scores_delta,
        experiment_id=_run_id,
        deadline_violations=_violations or None,
        deadline_days=deadline_days or None,
        rescheduled_moves=_rescheduled_moves or None,
        added_sessions=_added_log or None,
        not_added_sessions=_not_added_log or None,
        removed_sessions=_removed_log or None,
        not_removed_sessions=_not_removed_log or None,
        current_day=CURRENT_DAY,
    )

    if input("Générer le HTML final ? [Y/N] > ").lower() in ("y", "yes", ""):
        affichage_html_complet(
            current_schedule, nb_days,
            courses_list, rooms_list,
            "edt.html",
            lunch_debut_min=LUNCH_DEBUT_MIN, lunch_fin_min=LUNCH_FIN_MIN,
            room_unavailable_intervals=room_unavail or None,
            teacher_unavail_intervals=dict(teacher_unavail) or None,
            group_unavail_intervals=dict(group_unavail) or None,
            cancelled_items=all_truly_cancelled or None,
            deadline_violations=_violations or None,
            deadline_days=deadline_days or None,
            added_items=all_added or None,
            not_added_items=all_not_added or None,
            removed_items=all_removed or None,
            not_removed_items=all_not_removed or None,
            folder=_run_dir,
        )
        # Rapport heures — before/after si perturbation de type remplacement
        has_replacement = any(p["type"] in (4, 8, 9) for p in perturbations)
        affichage_html_heures(
            schedule=current_schedule,
            courses=courses_list,
            teachers=teachers_list,
            filename="heures.html",
            schedule_before=edt if has_replacement else None,
            removed_items=all_removed or None,
            folder=_run_dir,
        )
        print(f"Fichiers générés dans : {_run_dir}")