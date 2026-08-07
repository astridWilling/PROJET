import json
import os
from constraints import Constraint

_LOG_DEFAULT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Logs", "log.json")
from typing import List
import datetime
import time
from affichage import affichage_html_complet, recup_edt, save_edt
from constraints import ALL_CONSTRAINTS, CONSTRAINT_ABBR
from solver import solve
import itertools
import copy

#! Cette fonction crée un fichier JSONL (json Lines) donc il faut faire comme suit pour l'ouvrir correctement:
#? import json
#? with open("Logs/log.json") as f:
#?     logs = [json.loads(line) for line in f]


def logging(input_data: str, constraints: List[Constraint], status: str, score: float,
            max_searchtime: int, duration: float, output=None, logfile=_LOG_DEFAULT,
            nb_days: int = None, nb_slots_per_day: int = None, lunch_slots: list = None,
            callbacks: list = None, experiment_id: str = None,
            num_workers: int = None,
            nb_weeks: int = None,
            is_semester: bool = False,
            weeks: list = None,
            repartition: dict = None,
            balance_weight: int = None,
            ordering_weight: int = None,
            order_penalty: int = None,
            max_sessions_per_group_per_week: int = None,
            timeout_week_solve: int = None,
            timeout_per_week: int = None,
            week_solve_status: str = None,
            week_solve_objective: float = None,
            nb_unplaced: int = None):
    """
    Création de log pour chaque run.
    nb_days, nb_slots_per_day, lunch_slots : paramètres de la grille horaire.

    Paramètres généraux :
    num_workers        : nombre de threads CPU utilisés

    Paramètres mode semestre (tous None en mode semaine unique) :
    is_semester                   : True si résolution semestre
    weeks                         : [{week, status, score}, ...] — résultat de chaque semaine
    repartition                   : {week_index: nb_sessions} — distribution issue du week_solve
    balance_weight                : poids de l'équilibre inter-semaines
    ordering_weight               : poids du respect de l'ordre (grille horaire)
    order_penalty                 : poids de la pénalité d'ordre dans le week_solve
    max_sessions_per_group_per_week : cap utilisé dans le week_solve (auto ou manuel)
    timeout_week_solve            : timeout (s) de l'étape d'assignation aux semaines
    timeout_per_week              : timeout (s) par semaine pour la grille horaire
    week_solve_status             : statut du week_solve (OPTIMAL/FEASIBLE/UNKNOWN)
    week_solve_objective          : valeur de l'objectif du week_solve
    """
    os.makedirs(os.path.dirname(logfile), exist_ok=True)

    active_constraints = [{"name": c.__class__.__name__, "weight": c.weight, "is_hard": c.is_hard}
                          for c in constraints if c.is_active]
    pretty_duration = f"{int(duration // 60)}'{duration % 60:.2f}\""

    d = datetime.datetime.now()

    log_entry = {
        "timestamp":                      d.strftime("%Y-%m-%d %H:%M:%S"),
        "input":                          input_data,
        "nb_days":                        nb_days,
        "nb_slots_per_day":               nb_slots_per_day,
        "lunch_slots":                    lunch_slots,
        "constraints":                    active_constraints,
        "status":                         status,
        "score":                          score,
        "timeout_at":                     max_searchtime,
        "has_solution":                   status in ["OPTIMAL", "FEASIBLE"],
        "is_optimal":                     status == "OPTIMAL",
        "duration_sec":                   duration,
        "duration_pretty":                pretty_duration,
        "output":                         output,
        "callbacks":                      callbacks,
        "experiment_id":                  experiment_id,
        "num_workers":                    num_workers,
        "nb_weeks":                       nb_weeks,
        "is_semester":                    is_semester if is_semester else None,
        "weeks":                          weeks,
        "repartition":                    repartition,
        "balance_weight":                 balance_weight,
        "ordering_weight":                ordering_weight,
        "order_penalty":                  order_penalty,
        "max_sessions_per_group_per_week": max_sessions_per_group_per_week,
        "timeout_week_solve":             timeout_week_solve,
        "timeout_per_week":               timeout_per_week,
        "week_solve_status":              week_solve_status,
        "week_solve_objective":           week_solve_objective,
        "nb_unplaced":                    nb_unplaced,
    }

    with open(logfile, "a", encoding="utf-8") as f:
        f.write(json.dumps(log_entry) + "\n")


def migrate_log(logfile: str = _LOG_DEFAULT,
                default_nb_days: int = 3,
                default_nb_slots_per_day: int = 10,
                default_lunch_slots: list = None):
    """
    Backfille les entrées existantes du log qui n'ont pas encore nb_days,
    nb_slots_per_day et lunch_slots.  À appeler une seule fois après la mise à jour.

    Les entrées déjà complètes ne sont pas modifiées.
    Par défaut, utilise les paramètres petite/moyenne (3j × 10 slots, lunch=[2,3,4]).
    """
    if default_lunch_slots is None:
        default_lunch_slots = [2, 3, 4]

    with open(logfile, "r", encoding="utf-8") as f:
        entries = [json.loads(line) for line in f if line.strip()]

    modified = 0
    for entry in entries:
        if entry.get("nb_days") is None:
            entry["nb_days"]          = default_nb_days
            entry["nb_slots_per_day"] = default_nb_slots_per_day
            entry["lunch_slots"]      = default_lunch_slots
            modified += 1

    with open(logfile, "w", encoding="utf-8") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")

    print(f"[migrate_log] {modified} entrée(s) mises à jour sur {len(entries)} total.")


def get_log_entry(edt_name: str, logfile: str = _LOG_DEFAULT) -> dict | None:
    """
    Retourne la dernière entrée de log qui a produit l'EDT `edt_name`.
    Prévient si plusieurs entrées existent (cas d'un re-run avec le même nom).
    Retourne None si aucune entrée trouvée.
    """
    # Normalise : retire l'extension .json des deux côtés pour comparer
    needle = edt_name.removesuffix(".json")
    matches = []
    try:
        with open(logfile, encoding="utf-8") as f:
            for line in f:
                try:
                    entry = json.loads(line)
                    if (entry.get("output") or "").removesuffix(".json") == needle:
                        matches.append(entry)
                except Exception:
                    continue
    except FileNotFoundError:
        print(f"[get_log_entry] Fichier {logfile!r} introuvable.")
        return None

    if not matches:
        print(f"[get_log_entry] Aucune entrée trouvée pour l'EDT '{edt_name}'.")
        return None

    if len(matches) > 1:
        print(f"[get_log_entry] {len(matches)} entrées trouvées pour '{edt_name}' — "
              f"la plus récente est utilisée ({matches[-1]['timestamp']}).")

    return matches[-1]


def query_by_field(field: str, value, logfile: str = _LOG_DEFAULT) -> list:
    """
    Retourne toutes les entrées de log où entry[field] == value.

    Exemples :
        query_by_field("input", "Data/instance_petite.json")
        query_by_field("status", "OPTIMAL")
        query_by_field("output", "petite_NONE")

    Pour les champs liste (lunch_slots, constraints), la comparaison est exacte.
    Retourne une liste de dicts (vide si aucun résultat).
    """
    results = []
    try:
        with open(logfile, encoding="utf-8") as f:
            for line in f:
                try:
                    entry = json.loads(line)
                    if entry.get(field) == value:
                        results.append(entry)
                except Exception:
                    continue
    except FileNotFoundError:
        print(f"[query_by_field] Fichier {logfile!r} introuvable.")
        return []

    if not results:
        print(f"[query_by_field] Aucun résultat pour {field}={value!r}.")
    else:
        print(f"[query_by_field] {len(results)} entrée(s) trouvée(s) pour {field}={value!r}.")

    return results


def load_constraints_from_log(edt_name: str, logfile: str = _LOG_DEFAULT) -> list:
    """
    Retourne les contraintes actives du dernier run ayant produit l'EDT `edt_name`.

    Paramètre
    ---------
    edt_name : nom de l'EDT (sans extension), tel qu'il apparaît dans le champ "output" du log.

    Retourne
    --------
    Liste de dicts  [{"name": "NoGap", "weight": 1, "is_hard": False}, ...]
    Liste vide si aucun run trouvé pour cet EDT.
    """
    found = []
    try:
        with open(logfile, encoding="utf-8") as f:
            for line in f:
                try:
                    entry = json.loads(line)
                    if entry.get("output") == edt_name:
                        found = entry["constraints"]  # on garde la dernière occurrence
                except Exception:
                    continue
    except FileNotFoundError:
        print(f"[log] Fichier {logfile!r} introuvable — pas de contraintes chargées.")
    return found


def query_logs(logfile=_LOG_DEFAULT, status=None, input_name=None, output=None, constraints=None):
    """
    Cherche toutes les lignes du fichier logfile où le status, l'input_name, l'output, et les contraintes données sont présentes. Bel affichage des lignes correspondantes.

    constraints: liste de noms de contraintes à filtrer (ex: ["NoGap", "LongLunch"])
    """

    results = []

    with open(logfile, encoding="utf-8") as f:
        for line in f:
            try:
                entry = json.loads(line)
            except:
                continue

            # filtres

            if status and entry["status"] != status:
                continue

            if input_name and entry["input"] != input_name:
                continue

            if output and entry["output"] != output:
                continue

            if constraints:
                active_names = [c["name"] for c in entry["constraints"]]
                if not all(c in active_names for c in constraints):
                    continue

            results.append(entry)

    # ✅ affichage propre
    if not results:
        print("❌ Aucun résultat trouvé")
        return

    print(f"\n✅ {len(results)} résultats trouvés\n")

    for i, r in enumerate(results, 1):
        print(f"--- Run #{i} ---")
        print(f"🕒 {r['timestamp']}")
        print(f"📄 Input: {r['input']}")
        print(f"📊 Status: {r['status']}")
        print(f"⭐ Score: {r['score']}")
        print(f"⏱ Durée: {r['duration_pretty']}")
        print(f"🎯 Output: {r['output']}")

        cons = ", ".join(c["name"] for c in r["constraints"])
        print(f"⚙️ Contraintes: {cons}")

        print()



def run_all_experiments(input_file, base_config, courses, rooms, nb_days, lunch_slots, nb_slots_per_day, time_out="60", buildings=None):  # noqa: E501

    def generate_constraint_sets(base_config):
        n = len(base_config)

        for mask in itertools.product([0,1], repeat=n):
            config = copy.deepcopy(base_config)

            for i, active in enumerate(mask):
                config[i]["is_active"] = bool(active)

            yield config

    def build_name(input_file, constraints):
        # extraire "petite" depuis instance_petite.json par exemple
        base = input_file.replace("instance_", "").replace(".json", "")

        active_parts = []

        for c in constraints:
            if c.is_active:  # ⚠️ important
                abbr = CONSTRAINT_ABBR[c.__class__.__name__]
                active_parts.append(f"{abbr}{c.weight}")

        active_parts=sorted(active_parts)
        return base + ("_" + "_".join(active_parts) if active_parts else "_NONE")


    for i, conf in enumerate(generate_constraint_sets(base_config)):
        constraints = []
        for c in conf:
            cls = ALL_CONSTRAINTS[c["name"]]
            constraint = cls(
                is_hard=c["is_hard"],
                is_active=c["is_active"],
                weight=c["weight"],
                lunch_slots=c["lunch_slots"],
                nb_slots_per_day=c["nb_slots_per_day"]
            )
            constraints.append(constraint)

        nom=input_file.split("/")[-1]
        name = build_name(nom, constraints)+time_out
        print(f"\n===== RUN {i+1}: {name} =====")

        start = time.time()

        try:
            solver, slot, time_var, room_var, status, score, max_time, _ = solve(
                courses, rooms, nb_days, lunch_slots, nb_slots_per_day, constraints,
                buildings=buildings
            )

            duration = time.time() - start

            if status in ["OPTIMAL", "FEASIBLE"]:
                edt = recup_edt(solver, slot, courses, rooms, nb_days, nb_slots_per_day)
                save_edt(edt, name)
                output_file=f"edt_{name}.json"
                # output_file = f"edt_{name}.html"
                # affichage_html_complet(edt, nb_days, courses, rooms, filename=output_file)
            else:
                output_file = None

        except Exception as e:
            duration = time.time() - start

            print(f"❌ ERROR in run {i+1} {name}: {e}")

            status = "ERROR"
            score = None
            max_time = None
            output_file = None

        # ✅ TOUJOURS loggé
        logging(
            input_data=input_file,
            constraints=constraints,
            status=status,
            score=score,
            max_searchtime=max_time,
            duration=duration,
            output=output_file,
            nb_days=nb_days,
            nb_slots_per_day=nb_slots_per_day,
            lunch_slots=lunch_slots,
        )


def run_diff_timeout(input_file, config, courses, rooms, nb_days, lunch_slots, nb_slots_per_day, timeouts:List[int], buildings=None):
    constraints = []
    for c in config:
        cls = ALL_CONSTRAINTS[c["name"]]
        constraint = cls(
                        is_hard=c["is_hard"],
                        is_active=c["is_active"],
                        weight=c["weight"],
                        lunch_slots=c["lunch_slots"],
                        nb_slots_per_day=c["nb_slots_per_day"]
                        )
        constraints.append(constraint)


    def build_name(input_file, constraints):
        # extraire "petite" depuis instance_petite.json par exemple
        base = input_file.replace("instance_", "").replace(".json", "")

        active_parts = []

        for c in constraints:
            if c.is_active:  # ⚠️ important
                abbr = CONSTRAINT_ABBR[c.__class__.__name__]
                active_parts.append(f"{abbr}{c.weight}")

        active_parts=sorted(active_parts)
        return base + ("_" + "_".join(active_parts) if active_parts else "_NONE")


    for i, t in enumerate(timeouts):
        nom=input_file.split("/")[-1]   #On garde que le nom du fichier et non le chemin
        name = build_name(nom, constraints)+f"timeout{t}"
        print(f"\n===== RUN {i+1}: {name} =====")

        start = time.time()

        try:
            solver, slot, time_var, room_var, status, score, max_time, _ = solve(
                courses, rooms, nb_days, lunch_slots, nb_slots_per_day, constraints, t,
                buildings=buildings
            )

            duration = time.time() - start

            if status in ["OPTIMAL", "FEASIBLE"]:
                edt = recup_edt(solver, slot, courses, rooms, nb_days, nb_slots_per_day)
                save_edt(edt, name)
                output_file=f"{name}.json"
                # output_file = f"edt_{name}.html"
                # affichage_html_complet(edt, nb_days, courses, rooms, filename=output_file)
            else:
                output_file = None

        except Exception as e:
            duration = time.time() - start

            print(f"❌ ERROR in run {i+1} {name}: {e}")

            status = "ERROR"
            score = None
            max_time = None
            output_file = None

        # ✅ TOUJOURS loggé
        logging(
            input_data=input_file,
            constraints=constraints,
            status=status,
            score=score,
            max_searchtime=max_time,
            duration=duration,
            output=output_file,
            nb_days=nb_days,
            nb_slots_per_day=nb_slots_per_day,
            lunch_slots=lunch_slots,
        )

def run_cp_experiment(config: list, instance: str, t: int, n: int,
                      nb_days: int = 3, nb_slots_per_day: int = 10,
                      lunch_slots: list = None, logfile: str = _LOG_DEFAULT):
    """
    Lance n fois le solver sur instance avec timeout t et enregistre les callbacks
    de convergence (score vs wall_time) dans le log.

    Chaque run produit une entree de log avec :
      "callbacks": [[wall_time_s, score], ...]   # toutes les ameliorations trouvees
      "output": None  (run d analyse pure, pas d EDT sauvegarde)

    Parametres
    ----------
    config    : liste de dicts contraintes (meme format que main.py)
    instance  : chemin vers le fichier d instance  ex: "Data/instance_petite.json"
    t         : timeout en secondes
    n         : nombre de runs independants
    """
    if lunch_slots is None:
        lunch_slots = [2, 3, 4]

    from main import load_input
    courses, rooms, _, buildings, _ = load_input(instance)

    constraints = []
    for c in config:
        cls = ALL_CONSTRAINTS[c["name"]]
        constraints.append(cls(
            is_hard=c["is_hard"],
            is_active=c["is_active"],
            weight=c["weight"],
            lunch_slots=c.get("lunch_slots", lunch_slots),
            nb_slots_per_day=c.get("nb_slots_per_day", nb_slots_per_day),
        ))

    # Identifiant unique partagé par tous les n runs de cette expérience
    experiment_id = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    print(f"run_cp_experiment [{experiment_id}] : {n} runs x timeout={t}s sur {instance}")

    for i in range(n):
        print(f"  Run {i+1}/{n} ...", end=" ", flush=True)
        start = time.time()

        try:
            solver, slot, _, _, status, score, max_time, cbs = solve(
                courses, rooms, nb_days, lunch_slots, nb_slots_per_day,
                constraints, timeout=t, record_callbacks=True, buildings=buildings,
            )
            duration = time.time() - start
            callbacks_json = [list(pt) for pt in cbs] if cbs else []

        except Exception as e:
            duration = time.time() - start
            print(f"ERREUR: {e}")
            status, score, max_time, callbacks_json = "ERROR", None, t, []

        print(f"{status}  score={score}  {len(callbacks_json)} amelioration(s)  ({duration:.1f}s)")

        logging(
            input_data=instance,
            constraints=constraints,
            status=status,
            score=score,
            max_searchtime=max_time,
            duration=duration,
            output=None,
            nb_days=nb_days,
            nb_slots_per_day=nb_slots_per_day,
            lunch_slots=lunch_slots,
            callbacks=callbacks_json,
            logfile=logfile,
            experiment_id=experiment_id,
        )

    return experiment_id
