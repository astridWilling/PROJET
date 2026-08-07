import json
import os
import numpy as np

_HERE        = os.path.dirname(os.path.abspath(__file__))
_LOG_DEFAULT = os.path.join(_HERE, "Logs", "log.json")
_DATA_DIR    = os.path.join(_HERE, "Data")
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns


# def status_by_instance(logfile=_LOG_DEFAULT, max_lines=160):
#     data = []

#     with open(logfile, "r", encoding="utf-8") as f:
#         for i, line in enumerate(f):
#             if i >= max_lines:
#                 break
#             data.append(json.loads(line))

#     df = pd.DataFrame(data)

#     # extraction instance propre
#     df["instance"] = df["input"].apply(
#         lambda x: x.split("/")[-1].replace("instance_", "").replace(".json", "")
#     )

#     # compter tous les statuts possibles
#     all_status = ["OPTIMAL", "FEASIBLE", "UNKNOWN", "INFEASIBLE"]

#     result = df.groupby(["instance", "status"]).size().unstack(fill_value=0)

#     # s'assurer que tous les statuts existent
#     for s in all_status:
#         if s not in result.columns:
#             result[s] = 0

#     result = result[all_status]  # ordre propre

#     print(result)
#     return result


# def time_by_constraint(logfile=_LOG_DEFAULT, instance_name="complexe"):
#     data = []

#     with open(logfile, "r", encoding="utf-8") as f:
#         for i, line in enumerate(f):
#             data.append(json.loads(line))

#     df = pd.DataFrame(data)

#     df["instance"] = df["input"].apply(
#         lambda x: x.split("/")[-1].replace("instance_", "").replace(".json", "")
#     )

#     # filtrer instance
#     df = df[df["instance"] == instance_name]

#     # construire nom contrainte
#     def constraint_key(row):
#         if not row["constraints"]:
#             return "NONE"
#         return "_".join(sorted([c["name"] for c in row["constraints"]]))

#     df["constraint_set"] = df.apply(constraint_key, axis=1)

#     # moyenne temps
#     result = df.groupby("constraint_set")["duration_sec"].mean().sort_values()

#     # plot
#     result.plot(kind="bar", figsize=(10,5))
#     plt.title(f"Temps moyen par contrainte ({instance_name})")
#     plt.ylabel("Temps (s)")
#     plt.xticks(rotation=45)
#     plt.tight_layout()
#     plt.show()

#     return result


# def difficulty_by_constraint(logfile=_LOG_DEFAULT):
#     data = []

#     with open(logfile, "r", encoding="utf-8") as f:
#         for i, line in enumerate(f):
#             data.append(json.loads(line))

#     df = pd.DataFrame(data)

#     def has_constraint(row, name):
#         return int(any(c["name"] == name for c in row["constraints"]))

#     constraint_names = ["LongLunch", "LongLunchTeacher", "NoGap", "NoLateDay", "NoLateDayTeacher"]

#     for cname in constraint_names:
#         df[cname] = df.apply(lambda r: has_constraint(r, cname), axis=1)

#     df["hard"] = (df["status"] != "OPTIMAL").astype(int)

#     result = []
#     for cname in constraint_names:
#         sub = df[df[cname] == 1]
#         result.append({
#             "constraint": cname,
#             "difficulty": sub["hard"].mean()
#         })

#     res = pd.DataFrame(result).set_index("constraint")

#     sns.heatmap(res, annot=True, cmap="coolwarm")
#     plt.title("Impact des contraintes sur la difficulté")
#     plt.show()


# def score_distribution(logfile=_LOG_DEFAULT):
#     data = []

#     with open(logfile, "r", encoding="utf-8") as f:
#         for i, line in enumerate(f):
#             data.append(json.loads(line))

#     df = pd.DataFrame(data)
#     feasible = df[df["status"] == "FEASIBLE"]

#     plt.hist(feasible["score"], bins=10)
#     plt.title("Distribution des scores (solutions FEASIBLE)")
#     plt.xlabel("Score")
#     plt.ylabel("Fréquence")
#     plt.show()


# def impact_by_constraint(logfile=_LOG_DEFAULT):
#     data = []

#     with open(logfile, "r", encoding="utf-8") as f:
#         for i, line in enumerate(f):
#             data.append(json.loads(line))

#     df = pd.DataFrame(data)

#     rows = []

#     for cname in ["LongLunch", "LongLunchTeacher", "NoGap", "NoLateDay", "NoLateDayTeacher"]:
#         sub = df[df["constraints"].apply(lambda cs: any(c["name"] == cname for c in cs))]

#         if not sub.empty:
#             rows.append({
#                 "constraint": cname,
#                 "avg_score": sub["score"].mean(),
#                 "avg_time": sub["duration_sec"].mean(),
#                 "feasible_ratio": (sub["status"] == "FEASIBLE").mean()
#             })

#     result = pd.DataFrame(rows)

#     print(result)
#     return result


# def duration_histogram(logfile=_LOG_DEFAULT):
#     data = []

#     with open(logfile, "r", encoding="utf-8") as f:
#         for i, line in enumerate(f):
#             data.append(json.loads(line))

#     df = pd.DataFrame(data)

#     plt.hist(df["duration_sec"], bins=20)
#     plt.title("Distribution des temps de résolution")
#     plt.xlabel("Temps (s)")
#     plt.ylabel("Nombre de runs")
#     plt.show()


# def difficulty_bar(logfile=_LOG_DEFAULT):   #INUTILE!!!!
#     data = []

#     with open(logfile, "r", encoding="utf-8") as f:
#         for i, line in enumerate(f):
#             data.append(json.loads(line))

#     df = pd.DataFrame(data)

#     df["hard"] = (df["status"] != "OPTIMAL").astype(int)

#     by_instance = df.groupby("input")["hard"].mean()

#     by_instance.plot(kind="bar")
#     plt.title("Proportion de cas difficiles par instance")
#     plt.ylabel("Ratio FEASIBLE")
#     plt.show()


# def score_vs_nb_constraints(logfile=_LOG_DEFAULT):
#     data = []

#     with open(logfile, "r", encoding="utf-8") as f:
#         for i, line in enumerate(f):
#             data.append(json.loads(line))

#     df = pd.DataFrame(data)

#     df["nb_constraints"] = df["constraints"].apply(len)

#     res = df.groupby("nb_constraints")["score"].mean()

#     res.plot(marker='o')
#     plt.title("Score moyen vs nb de contraintes")
#     plt.xlabel("Nombre de contraintes actives")
#     plt.ylabel("Score moyen")
#     plt.show()


# def duration_by_status(logfile=_LOG_DEFAULT):
#     data = []

#     with open(logfile, "r", encoding="utf-8") as f:
#         for i, line in enumerate(f):
#             data.append(json.loads(line))

#     df = pd.DataFrame(data)

#     for status in ["OPTIMAL", "FEASIBLE"]:
#         sub = df[df["status"] == status]
#         plt.hist(sub["duration_sec"], alpha=0.5, label=status)

#     plt.legend()
#     plt.title("Temps par type de solution")
#     plt.show()



# status_by_instance()
# time_by_constraint()
# difficulty_by_constraint()
# score_distribution()
# impact_by_constraint()
# duration_histogram()
# difficulty_bar()
# score_vs_nb_constraints()
# duration_by_status()



############ Bonnes fonctions d'analyse
def explain_runtime(logfile=_LOG_DEFAULT):
    data = []

    with open(logfile, "r", encoding="utf-8") as f:
        for i, line in enumerate(f):
            data.append(json.loads(line))

    df = pd.DataFrame(data)

    # nb contraintes
    df["nb_constraints"] = df["constraints"].apply(len)

    # taille instance (approx via nom)
    df["instance_size"] = df["input"].apply(
        lambda x: x.split("_")[-1].replace(".json", "")
    )

    # scatter
    plt.figure(figsize=(10,5))

    for size in df["instance_size"].unique():
        sub = df[df["instance_size"] == size]
        plt.scatter(
            sub["nb_constraints"],
            sub["duration_sec"],
            label=size,
            alpha=0.7
        )

    plt.xlabel("Nombre de contraintes actives")
    plt.ylabel("Temps (s)")
    plt.title("Temps vs complexité du modèle")
    plt.legend()
    plt.grid()
    plt.show()


def score_by_constraints(logfile=_LOG_DEFAULT):
    data = []

    with open(logfile, "r", encoding="utf-8") as f:
        for i, line in enumerate(f):
            data.append(json.loads(line))

    df = pd.DataFrame(data)
    df = df[df["nb_weeks"].isna()]  # exclure les runs semestre (scores non comparables)

    df["nb_constraints"] = df["constraints"].apply(len)

    res = df.groupby("nb_constraints")["score"].mean()

    res.plot(marker='o')
    plt.title("Score moyen vs nombre de contraintes")
    plt.xlabel("Nombre de contraintes")
    plt.ylabel("Score")
    plt.grid()
    plt.show()

def runtime_by_constraints(logfile=_LOG_DEFAULT):
    data = []

    with open(logfile, "r", encoding="utf-8") as f:
        for i, line in enumerate(f):
            data.append(json.loads(line))

    df = pd.DataFrame(data)
    df = df[df["nb_weeks"].isna()]  # exclure les runs semestre

    df["nb_constraints"] = df["constraints"].apply(len)

    res = df.groupby("nb_constraints")["duration_sec"].mean()

    res.plot(marker='o')
    plt.title("Temps moyen vs nombre de contraintes")
    plt.xlabel("Nombre de contraintes")
    plt.ylabel("Temps moyen (s)")
    plt.grid()
    plt.show()

def runtime_by_instance(logfile=_LOG_DEFAULT):
    data = []

    with open(logfile, "r", encoding="utf-8") as f:
        for i, line in enumerate(f):
            data.append(json.loads(line))

    df = pd.DataFrame(data)
    df = df[df["nb_weeks"].isna()]  # exclure les runs semestre (durées non comparables)

    df["instance"] = df["input"].apply(
        lambda x: x.split("/")[-1].replace("instance_", "").replace(".json", "")
    )

    df.boxplot(column="duration_sec", by="instance")

    plt.title("Temps de résolution par instance")
    plt.suptitle("")
    plt.ylabel("Temps (s)")
    plt.xticks(rotation=45)
    plt.show()

def score_vs_time_colored(logfile=_LOG_DEFAULT):
    data = []

    with open(logfile, "r", encoding="utf-8") as f:
        for i, line in enumerate(f):
            data.append(json.loads(line))

    df = pd.DataFrame(data)
    df = df[df["nb_weeks"].isna()]  # exclure les runs semestre

    df["nb_constraints"] = df["constraints"].apply(len)

    plt.scatter(
        df["duration_sec"],
        df["score"],
        c=df["nb_constraints"],
        cmap="viridis"
    )

    plt.colorbar(label="nb contraintes")
    plt.xlabel("Temps")
    plt.ylabel("Score")
    plt.title("Score vs Temps (coloré par complexité)")
    plt.show()

def pareto_plot(logfile=_LOG_DEFAULT, instance_name="complexe"):
    data = []

    with open(logfile, "r", encoding="utf-8") as f:
        for i, line in enumerate(f):
            data.append(json.loads(line))

    df = pd.DataFrame(data)

    df["instance"] = df["input"].apply(
        lambda x: x.split("/")[-1].replace("instance_", "").replace(".json", "")
    )

    df = df[df["nb_weeks"].isna()]  # exclure les runs semestre (frontière Pareto incohérente)
    df = df[df["instance"] == instance_name]

    # garder seulement solutions valides
    df = df[df["status"].isin(["OPTIMAL", "FEASIBLE"])]

    # calcul pareto
    pareto = []

    for i, row in df.iterrows():
        dominated = False
        for j, other in df.iterrows():
            if (
                other["score"] <= row["score"]
                and other["duration_sec"] <= row["duration_sec"]
                and (other["score"] < row["score"] or other["duration_sec"] < row["duration_sec"])
            ):
                dominated = True
                break

        if not dominated:
            pareto.append(row)

    pareto_df = pd.DataFrame(pareto)

    # plot
    plt.scatter(df["duration_sec"], df["score"], label="All")
    plt.scatter(pareto_df["duration_sec"], pareto_df["score"], color="red", label="Pareto")

    plt.xlabel("Temps (s)")
    plt.ylabel("Score")
    plt.title(f"Pareto front ({instance_name})")
    plt.legend()
    plt.grid()
    plt.show()

    return pareto_df



############ Nouvelles fonctions d'analyse

def timeout_analysis(logfile=_LOG_DEFAULT):
    """
    Montre à quel point chaque run a "consommé" son timeout.
    Utile dès le premier run : révèle si tes solutions FEASIBLE sont trouvées
    confortablement ou à la dernière seconde.

    Prérequis : >= 1 run dans le log.
    """
    with open(logfile, "r", encoding="utf-8") as f:
        data = [json.loads(line) for line in f]

    df = pd.DataFrame(data)
    df = df[df["timeout_at"].notna() & (df["timeout_at"] > 0)].copy()
    df["saturation"] = df["duration_sec"] / df["timeout_at"]

    status_colors = {
        "OPTIMAL":    "#2ecc71",
        "FEASIBLE":   "#f39c12",
        "UNKNOWN":    "#e74c3c",
        "INFEASIBLE": "#8e44ad",
    }

    fig, axes = plt.subplots(1, 2, figsize=(13, 5))

    # --- Gauche : scatter durée vs timeout, coloré par status ---
    for status, grp in df.groupby("status"):
        axes[0].scatter(
            grp["timeout_at"], grp["duration_sec"],
            label=status, color=status_colors.get(status, "grey"),
            alpha=0.75, edgecolors="white", linewidths=0.4, s=60
        )
    lim = df["timeout_at"].max() * 1.05
    axes[0].plot([0, lim], [0, lim], "k--", lw=0.8, alpha=0.4, label="100% timeout")
    axes[0].set_xlabel("Timeout configuré (s)")
    axes[0].set_ylabel("Durée réelle (s)")
    axes[0].set_title("Durée réelle vs timeout")
    axes[0].legend(fontsize=8)
    axes[0].grid(alpha=0.3)

    # --- Droite : histogramme de saturation par status ---
    bins = np.linspace(0, 1.05, 22)
    for status in ["OPTIMAL", "FEASIBLE", "UNKNOWN", "INFEASIBLE"]:
        grp = df[df["status"] == status]
        if grp.empty:
            continue
        axes[1].hist(
            grp["saturation"].clip(upper=1.0),
            bins=bins, alpha=0.6,
            label=f"{status} (n={len(grp)})",
            color=status_colors.get(status, "grey")
        )

    axes[1].axvline(0.9, color="red", linestyle="--", lw=1, label="seuil 90%")
    near_timeout = (df["saturation"] >= 0.9).mean() * 100
    axes[1].set_xlabel("Saturation (durée / timeout)")
    axes[1].set_ylabel("Nombre de runs")
    axes[1].set_title(f"Distribution de saturation\n({near_timeout:.0f}% des runs >= 90% du timeout)")
    axes[1].legend(fontsize=8)
    axes[1].grid(alpha=0.3)

    plt.suptitle("Analyse timeout — confort de résolution", fontsize=12, y=1.01)
    plt.tight_layout()
    plt.show()

    print(f"\nResume saturation par status :")
    print(df.groupby("status")["saturation"].describe().round(3))
    return df[["timestamp", "input", "status", "duration_sec", "timeout_at", "saturation"]]


def constraint_marginal_cost(logfile=_LOG_DEFAULT, instance_name=None):
    """
    Calcule le cout marginal de chaque contrainte : différence de durée et de score
    quand on l'active vs quand elle est absente, toutes autres contraintes égales par ailleurs.

    Prérequis : runs avec DIFFÉRENTES combinaisons de contraintes (idéalement les 32 runs
    de run_all_experiments). Avec 14 runs identiques -> inutile.

    instance_name : filtrer sur une instance (ex: "petite"). None = toutes.
    """
    with open(logfile, "r", encoding="utf-8") as f:
        data = [json.loads(line) for line in f]

    df = pd.DataFrame(data)
    df = df[df["nb_weeks"].isna()]  # exclure les runs semestre (deltas de score invalides)
    df["instance"] = df["input"].apply(
        lambda x: x.split("/")[-1].replace("instance_", "").replace(".json", "")
    )
    if instance_name:
        df = df[df["instance"] == instance_name]

    constraint_names = ["LongLunch", "LongLunchTeacher", "NoGap", "NoLateDay", "NoLateDayTeacher"]

    for cname in constraint_names:
        df[cname] = df["constraints"].apply(
            lambda cs: int(any(c["name"] == cname for c in cs))
        )

    rows = []
    for cname in constraint_names:
        with_c    = df[df[cname] == 1]
        without_c = df[df[cname] == 0]

        if with_c.empty or without_c.empty:
            continue

        delta_time  = with_c["duration_sec"].mean() - without_c["duration_sec"].mean()
        delta_score = with_c["score"].mean()         - without_c["score"].mean()
        feasible_with    = with_c["has_solution"].mean()    if "has_solution" in with_c.columns else None
        feasible_without = without_c["has_solution"].mean() if "has_solution" in without_c.columns else None

        rows.append({
            "constraint":       cname,
            "delta_duree_s":    delta_time,
            "delta_score":      delta_score,
            "faisabilite_avec": feasible_with,
            "faisabilite_sans": feasible_without,
            "n_avec":           len(with_c),
            "n_sans":           len(without_c),
        })

    if not rows:
        print("Pas assez de variete dans les runs pour calculer les couts marginaux.")
        return

    res = pd.DataFrame(rows).set_index("constraint")
    print(res.to_string())

    fig, axes = plt.subplots(1, 2, figsize=(13, 5))
    title_suffix = f" — {instance_name}" if instance_name else ""

    colors_time  = ["#e74c3c" if v > 0 else "#2ecc71" for v in res["delta_duree_s"]]
    colors_score = ["#e74c3c" if v > 0 else "#2ecc71" for v in res["delta_score"]]

    axes[0].bar(res.index, res["delta_duree_s"], color=colors_time, edgecolor="white")
    axes[0].axhline(0, color="black", lw=0.8)
    axes[0].set_title(f"Cout marginal sur la duree{title_suffix}")
    axes[0].set_ylabel("delta duree (s)  [rouge = ralentit]")
    axes[0].tick_params(axis="x", rotation=30)
    axes[0].grid(axis="y", alpha=0.3)

    axes[1].bar(res.index, res["delta_score"], color=colors_score, edgecolor="white")
    axes[1].axhline(0, color="black", lw=0.8)
    axes[1].set_title(f"Cout marginal sur le score{title_suffix}")
    axes[1].set_ylabel("delta score  [rouge = degrade]")
    axes[1].tick_params(axis="x", rotation=30)
    axes[1].grid(axis="y", alpha=0.3)

    plt.suptitle("Cout marginal par contrainte", fontsize=12, y=1.01)
    plt.tight_layout()
    plt.show()

    return res


def instance_complexity_vs_runtime(logfile=_LOG_DEFAULT, instances_dir=_DATA_DIR):
    """
    Croise le log avec les fichiers d'instance pour voir comment la taille du problème
    (nb_sessions, nb_salles, ratio sessions/salles) impacte le temps de résolution.

    Prérequis : plusieurs instances DIFFÉRENTES dans le log (petite, moyenne, univ, etc.).
    Les fichiers JSON d'instance doivent être accessibles depuis instances_dir.
    """
    with open(logfile, "r", encoding="utf-8") as f:
        data = [json.loads(line) for line in f]

    df = pd.DataFrame(data)
    df = df[df["nb_weeks"].isna()]  # exclure les runs semestre (métriques d'instance incompatibles)

    instance_metrics = {}
    for input_path in df["input"].unique():
        candidates = [input_path, os.path.join(instances_dir, os.path.basename(input_path))]
        found = next((p for p in candidates if os.path.exists(p)), None)
        if found is None:
            print(f"[!] Fichier introuvable : {input_path} — ignore")
            continue

        with open(found, encoding="utf-8") as f_inst:
            inst = json.load(f_inst)

        courses = inst.get("courses", [])
        rooms   = inst.get("rooms", [])
        nb_sessions = sum(c["slots_per_week"] for c in courses)

        by_type = {}
        for r in rooms:
            for rt in r.get("room_types", []):
                by_type[rt] = by_type.get(rt, 0) + 1

        instance_metrics[input_path] = {
            "nb_courses":  len(courses),
            "nb_sessions": nb_sessions,
            "nb_rooms":    len(rooms),
            "nb_CM":       by_type.get("CM", 0),
            "nb_TD":       by_type.get("TD", 0),
            "nb_INFO":     by_type.get("INFO", 0),
            "label":       os.path.basename(input_path).replace("instance_", "").replace(".json", ""),
        }

    if not instance_metrics:
        print("Aucune instance trouvee — verifier instances_dir.")
        return

    df["_metrics"] = df["input"].map(instance_metrics)
    df = df[df["_metrics"].notna()].copy()
    for key in ["nb_courses", "nb_sessions", "nb_rooms", "nb_CM", "nb_TD", "nb_INFO", "label"]:
        df[key] = df["_metrics"].apply(lambda m: m[key])

    agg = df.groupby("label").agg(
        nb_sessions=("nb_sessions",  "first"),
        nb_rooms=("nb_rooms",        "first"),
        nb_TD=("nb_TD",              "first"),
        nb_INFO=("nb_INFO",          "first"),
        avg_duration=("duration_sec", "mean"),
        min_duration=("duration_sec", "min"),
        max_duration=("duration_sec", "max"),
        n_runs=("duration_sec",       "count"),
        pct_feasible=("has_solution", "mean"),
    ).reset_index()

    if agg.empty:
        print("Pas assez de donnees apres agregation.")
        return

    print(agg[["label","nb_sessions","nb_rooms","avg_duration","pct_feasible","n_runs"]].to_string(index=False))

    fig, axes = plt.subplots(1, 3, figsize=(16, 5))

    # --- 1. nb_sessions -> durée ---
    sc = axes[0].scatter(
        agg["nb_sessions"], agg["avg_duration"],
        s=agg["nb_rooms"] * 8, c=agg["pct_feasible"],
        cmap="RdYlGn", vmin=0, vmax=1, edgecolors="grey", linewidths=0.5
    )
    for _, row in agg.iterrows():
        axes[0].annotate(row["label"], (row["nb_sessions"], row["avg_duration"]),
                         fontsize=8, ha="left", va="bottom", xytext=(4, 2),
                         textcoords="offset points")
    plt.colorbar(sc, ax=axes[0], label="% faisable")
    axes[0].set_xlabel("Nb sessions a placer")
    axes[0].set_ylabel("Duree moyenne (s)")
    axes[0].set_title("Sessions -> temps\n(taille du cercle = nb salles)")
    axes[0].grid(alpha=0.3)

    # --- 2. nb_rooms -> durée ---
    sc2 = axes[1].scatter(
        agg["nb_rooms"], agg["avg_duration"],
        s=80, c=agg["nb_sessions"], cmap="plasma",
        edgecolors="grey", linewidths=0.5
    )
    for _, row in agg.iterrows():
        axes[1].annotate(row["label"], (row["nb_rooms"], row["avg_duration"]),
                         fontsize=8, ha="left", va="bottom", xytext=(4, 2),
                         textcoords="offset points")
    plt.colorbar(sc2, ax=axes[1], label="nb sessions")
    axes[1].set_xlabel("Nb salles")
    axes[1].set_ylabel("Duree moyenne (s)")
    axes[1].set_title("Salles -> temps\n(couleur = nb sessions)")
    axes[1].grid(alpha=0.3)

    # --- 3. ratio sessions/salles -> durée ---
    agg["ratio"] = agg["nb_sessions"] / agg["nb_rooms"]
    axes[2].scatter(
        agg["ratio"], agg["avg_duration"],
        s=80, color="#3498db", edgecolors="grey", linewidths=0.5
    )
    for _, row in agg.iterrows():
        axes[2].annotate(row["label"], (row["ratio"], row["avg_duration"]),
                         fontsize=8, ha="left", va="bottom", xytext=(4, 2),
                         textcoords="offset points")
    axes[2].set_xlabel("Ratio sessions / salles")
    axes[2].set_ylabel("Duree moyenne (s)")
    axes[2].set_title("Pression sur les salles -> temps")
    axes[2].grid(alpha=0.3)

    plt.suptitle("Impact de la taille de l'instance sur le temps de resolution", fontsize=12, y=1.01)
    plt.tight_layout()
    plt.show()

    return agg


def score_vs_runtime(logfile=_LOG_DEFAULT, instance="moyenne", config=None):
    data = []
    with open(logfile, "r", encoding="utf-8") as f:
        for line in f:
            data.append(json.loads(line))

    df = pd.DataFrame(data)
    df = df[df["nb_weeks"].isna()]  # exclure les runs semestre

    # Filtre instance
    df = df[df["input"].str.contains(instance)]

    # Filtre config (actives uniquement)
    def match_constraints(row):
        active = sorted([
            c["name"]
            for c in row["constraints"]
            if c.get("is_active", True)
        ])
        
        target = sorted([
                c["name"]
                for c in config
                if c.get("is_active", True)
            ])

        return active == target

    if config is not None:
        df = df[df.apply(match_constraints, axis=1)]

    # Garder runs valides
    df = df[df["status"].isin(["OPTIMAL", "FEASIBLE"])]
    df = df.sort_values("duration_sec")

    #Meilleure progression
    best_scores = []
    current_best = float("inf")
    for _, row in df.iterrows():
        if row["score"] < current_best:
            current_best = row["score"]
        best_scores.append(current_best)

    #Récupérer le nom des contraintes actives dans config
    def constraint_label(constraints):
        if not constraints:
            return "NONE"

        names = [
            c["name"]
            for c in constraints
            if c.get("is_active", True)
        ]

        return "_".join(sorted(names))
    label = constraint_label(config)

    #plot
    plt.plot(df["duration_sec"], best_scores, marker='o')

    plt.xlabel("Durée (s)")
    plt.ylabel("Meilleur score trouvé")
    plt.title(f"Convergence ({instance} - {label})")

    plt.grid()
    plt.show()





def list_cp_experiments(logfile=_LOG_DEFAULT, instance=None):
    """
    Liste toutes les expériences run_cp_experiment disponibles dans le log
    (entrées avec un experiment_id et des callbacks).

    Utile pour trouver l'experiment_id à passer à plot_cp_experiment.
    """
    with open(logfile, "r", encoding="utf-8") as f:
        data = [json.loads(line) for line in f]

    seen = {}
    for entry in data:
        eid = entry.get("experiment_id")
        if not eid or not entry.get("callbacks"):
            continue
        if instance and entry.get("input") != instance:
            continue
        if eid not in seen:
            seen[eid] = {"instance": entry["input"], "t": entry.get("timeout_at"),
                         "n": 0, "timestamp": entry["timestamp"]}
        seen[eid]["n"] += 1

    if not seen:
        print("Aucune expérience run_cp_experiment trouvée dans le log.")
        return {}

    print(f"{'experiment_id':<20}  {'instance':<35}  {'t':>5}s  {'n':>3} runs  timestamp")
    print("-" * 80)
    for eid, info in sorted(seen.items()):
        print(f"{eid:<20}  {info['instance']:<35}  {str(info['t']):>5}   {info['n']:>3}       {info['timestamp']}")
    return seen


def plot_cp_experiment(logfile=_LOG_DEFAULT, instance=None,
                       t=None, experiment_id=None):
    """
    Trace les courbes de convergence score vs temps issues de run_cp_experiment.

    - Une courbe fine par run (step function, semi-transparente)
    - La courbe moyenne en gras (interpolation aux mêmes points de temps)

    Paramètres
    ----------
    instance      : chemin exact de l'instance (filtre)
    t             : timeout (filtre optionnel)
    experiment_id : ID retourné par run_cp_experiment(), ou affiché par list_cp_experiments().
                    Si None → prend l'expérience la plus récente pour cette instance+t.

    Prérequis : avoir lancé run_cp_experiment() au préalable.
    """
    with open(logfile, "r", encoding="utf-8") as f:
        data = [json.loads(line) for line in f]

    # Sélection des entrées candidates (runs semaine unique uniquement)
    candidates = [
        e for e in data
        if (instance is None or e.get("input") == instance)
        and e.get("callbacks")
        and (t is None or e.get("timeout_at") == t)
        and (experiment_id is None or e.get("experiment_id") == experiment_id)
        and e.get("nb_weeks") is None
    ]

    if not candidates:
        print(f"Aucun run trouvé. Vérifiez instance, t et experiment_id.")
        print("Expériences disponibles :")
        list_cp_experiments(logfile, instance)
        return

    # Si experiment_id non précisé → prendre le plus récent
    if experiment_id is None:
        latest_id = max(
            (e.get("experiment_id") for e in candidates if e.get("experiment_id")),
            default=None
        )
        if latest_id:
            candidates = [e for e in candidates if e.get("experiment_id") == latest_id]
            print(f"experiment_id non précisé → utilisation du plus récent : {latest_id}")

    runs = [e["callbacks"] for e in candidates]

    if not runs:
        print(f"Aucun run avec callbacks pour instance='{instance}'"
              + (f" t={t}s" if t else "") + ".")
        return

    timeout_val = t if t is not None else max(
        e.get("timeout_at", 0) for e in candidates
    )
    exp_id_label = candidates[0].get("experiment_id", "?")

    # Grille temporelle commune pour l'interpolation (200 points)
    t_grid = np.linspace(0, timeout_val, 200)

    def interp_step(cbs, t_grid):
        """Interpolation en escalier d'une liste [[t, score], ...]."""
        times  = np.array([p[0] for p in cbs])
        scores = np.array([p[1] for p in cbs])
        result = np.full(len(t_grid), np.nan)
        for k, tq in enumerate(t_grid):
            mask = times <= tq
            if mask.any():
                result[k] = scores[mask][-1]
        return result

    # Vérifier qu'au moins un run a des points
    runs_with_data = [r for r in runs if r]
    if not runs_with_data:
        print(f"Aucun callback enregistré pour cette expérience "
              f"(le solver n'a peut-être trouvé aucune solution dans le timeout).")
        return None

    curves = np.array([interp_step(r, t_grid) for r in runs])

    fig, ax = plt.subplots(figsize=(11, 5))

    # Courbes individuelles (fines, semi-transparentes)
    for curve in curves:
        valid = ~np.isnan(curve)
        if valid.any():
            ax.step(t_grid[valid], curve[valid], where="post",
                    alpha=0.3, linewidth=1, color="#3498db")

    # Courbe moyenne (ignore les NaN — avant la 1re solution de certains runs)
    with np.errstate(all="ignore"):
        mean_curve = np.nanmean(curves, axis=0)
    valid_mean = ~np.isnan(mean_curve)
    if valid_mean.any():
        ax.step(t_grid[valid_mean], mean_curve[valid_mean], where="post",
                linewidth=2.5, color="#e74c3c", label=f"Moyenne ({len(runs)} runs)")

    # Points bruts des callbacks (markers)
    for cbs in runs:
        ts = [p[0] for p in cbs]
        ss = [p[1] for p in cbs]
        ax.scatter(ts, ss, s=18, color="#3498db", alpha=0.4, zorder=3)

    instance_label = (os.path.basename(instance).replace("instance_", "").replace(".json", "")
                      if instance else "toutes instances")
    ax.set_xlabel("Wall time (s)")
    ax.set_ylabel("Score (objectif à minimiser)")
    ax.set_title(f"Convergence du solver — {instance_label}"
                 + (f"  timeout={timeout_val}s" if timeout_val else "")
                 + f"  ({len(runs)} runs)"
                 + f"\n[{exp_id_label}]")
    ax.legend()
    ax.grid(alpha=0.3)
    plt.tight_layout()
    plt.show()

    # Résumé numérique
    final_scores = [r[-1][1] for r in runs if r]
    first_times  = [r[0][0]  for r in runs if r]
    print(f"\n{len(runs)} runs  |  timeout={timeout_val}s")
    print(f"Score final  : moy={np.mean(final_scores):.1f}  min={np.min(final_scores):.1f}  max={np.max(final_scores):.1f}")
    print(f"1re solution : moy={np.mean(first_times):.2f}s  min={np.min(first_times):.2f}s  max={np.max(first_times):.2f}s")

    return {"runs": runs, "t_grid": t_grid, "curves": curves, "mean_curve": mean_curve}


# ===========================================================================
# ANALYSE MODE SEMESTRE
# ===========================================================================

STATUS_COLORS = {
    "OPTIMAL":    "#2ecc71",
    "GREEDY":     "#3498db",
    "FEASIBLE":   "#f39c12",
    "INFEASIBLE": "#e74c3c",
    "UNKNOWN":    "#95a5a6",
    "MISSING":    "#bdc3c7",
}
STATUS_ORDER = ["OPTIMAL", "FEASIBLE", "GREEDY", "UNKNOWN", "INFEASIBLE", "MISSING"]


def _load_semester_entries(logfile=_LOG_DEFAULT, instance=None):
    """Charge les entrées is_semester=True du log, filtrées optionnellement par instance."""
    with open(logfile, "r", encoding="utf-8") as f:
        data = [json.loads(line) for line in f]
    entries = [e for e in data if e.get("is_semester")]
    if instance:
        entries = [e for e in entries if instance in e.get("input", "")]
    return entries


def _inst_label(input_path):
    return os.path.basename(input_path).replace("instance_", "").replace(".json", "")


def analyze_semester(instance=None, logfile=_LOG_DEFAULT):
    """
    Vue d'ensemble des runs semestre enregistrés dans le log.

    Pour chaque run : tableau récap (instance, nb_weeks, status global, score,
    durée, balance_weight, ordering_weight, nb semaines résolues).

    Pour le run le plus récent de chaque instance : deux graphes —
      - répartition sessions/semaine + statut de chaque semaine
      - score par semaine (barres)

    instance : filtre optionnel (sous-chaîne du chemin d'instance, ex: "inge")
    """
    entries = _load_semester_entries(logfile, instance)
    if not entries:
        print("Aucun run semestre trouvé dans le log" + (f" pour '{instance}'" if instance else "") + ".")
        return

    # ── Tableau récap ──────────────────────────────────────────────────────
    print(f"\n{'#':<4} {'Instance':<35} {'Wks':>3} {'Status':<12} {'Score':>8} "
          f"{'Durée':>8} {'bw':>3} {'ow':>3} {'op':>4} {'mspgw':>6} "
          f"{'t_ws':>5} {'t_pw':>5} {'thr':>4} {'WS_stat':<10} {'Résolues':>9}  Timestamp")
    print("─" * 150)
    for i, e in enumerate(entries):
        weeks = e.get("weeks") or []
        nb_solved = sum(1 for w in weeks if w.get("status") in ("OPTIMAL", "FEASIBLE"))
        nb_w  = e.get("nb_weeks") or len(weeks)
        dur   = e.get("duration_sec", 0)
        score = e.get("score")
        def _s(v, fmt=None): return (fmt % v if fmt else str(v)) if v is not None else "—"
        print(f"{i:<4} {_inst_label(e.get('input','?')):<35} {nb_w:>3} "
              f"{e.get('status','?'):<12} {_s(score,'%.1f'):>8} "
              f"{int(dur//60)}m{dur%60:.0f}s{'':<2}"
              f"{_s(e.get('balance_weight')):>3} {_s(e.get('ordering_weight')):>3} "
              f"{_s(e.get('order_penalty')):>4} {_s(e.get('max_sessions_per_group_per_week')):>6} "
              f"{_s(e.get('timeout_week_solve'))+'s':>5} {_s(e.get('timeout_per_week'))+'s':>5} "
              f"{_s(e.get('num_workers')):>4} "
              f"{e.get('week_solve_status','—'):<10} "
              f"{nb_solved:>3}/{nb_w:<4}  {e.get('timestamp','')}")

    # ── Graphes : dernier run par instance ────────────────────────────────
    by_inst = {}
    for e in entries:
        lbl = _inst_label(e.get("input", "?"))
        by_inst[lbl] = e  # écrase → on garde le dernier

    n_inst = len(by_inst)
    if n_inst == 0:
        return

    fig, axes = plt.subplots(2, n_inst, figsize=(7 * n_inst, 9))
    if n_inst == 1:
        axes = [[axes[0]], [axes[1]]]  # normalise en 2D

    for col, (lbl, e) in enumerate(by_inst.items()):
        weeks  = e.get("weeks") or []
        rpart  = e.get("repartition") or {}
        nb_w   = e.get("nb_weeks") or len(weeks)
        week_ids = list(range(nb_w))

        status_map = {w["week"]: w["status"] for w in weeks}
        score_map  = {w["week"]: w["score"]  for w in weeks}
        rep_map    = {int(k): v for k, v in rpart.items()} if rpart else {}

        # ── Ligne 1 : répartition + statut ────────────────────────────
        ax1 = axes[0][col]
        rep_vals = [rep_map.get(w, 0) for w in week_ids]
        bar_colors = [STATUS_COLORS.get(status_map.get(w, "MISSING"), "#bdc3c7") for w in week_ids]
        bars = ax1.bar(week_ids, rep_vals, color=bar_colors, edgecolor="white", linewidth=0.5)
        ax1.set_xlabel("Semaine")
        ax1.set_ylabel("Nb sessions")
        bw  = e.get("balance_weight",    "?")
        ow  = e.get("ordering_weight",   "?")
        tws = e.get("timeout_week_solve", "?")
        tpw = e.get("timeout_per_week",   "?")
        ax1.set_title(f"{lbl}\nbw={bw}  ow={ow}  t_wsolve={tws}s  t_week={tpw}s", fontsize=9)
        ax1.set_xticks(week_ids)
        ax1.set_xticklabels([str(w) for w in week_ids], fontsize=7)
        ax1.grid(axis="y", alpha=0.3)
        # Légende statuts
        handles = [plt.Rectangle((0,0),1,1, color=STATUS_COLORS[s], label=s)
                   for s in STATUS_ORDER if any(status_map.get(w) == s for w in week_ids)]
        ax1.legend(handles=handles, fontsize=7, loc="upper right")

        # ── Ligne 2 : score par semaine ───────────────────────────────
        ax2 = axes[1][col]
        score_vals = [score_map.get(w) for w in week_ids]
        bar_colors2 = [STATUS_COLORS.get(status_map.get(w, "MISSING"), "#bdc3c7") for w in week_ids]
        valid_scores = [(w, s) for w, s in zip(week_ids, score_vals) if s is not None]
        if valid_scores:
            ws, ss = zip(*valid_scores)
            ax2.bar(ws, ss,
                    color=[bar_colors2[w] for w in ws],
                    edgecolor="white", linewidth=0.5)
        ax2.set_xlabel("Semaine")
        ax2.set_ylabel("Score (à minimiser)")
        total_score = e.get("score")
        total_str = f"{total_score:.1f}" if total_score is not None else "—"
        ax2.set_title(f"Score par semaine  (total={total_str})", fontsize=10)
        ax2.set_xticks(week_ids)
        ax2.set_xticklabels([str(w) for w in week_ids], fontsize=7)
        ax2.grid(axis="y", alpha=0.3)

    plt.suptitle("Analyse semestre — dernier run par instance", fontsize=13, y=1.01)
    plt.tight_layout()
    plt.show()
    return entries


def compare_semester(instance_a, instance_b, logfile=_LOG_DEFAULT):
    """
    Comparaison côte-à-côte de deux instances semestre (dernier run de chacune).

    Graphes :
      1. Statuts par semaine (barres empilées normalisées, côte-à-côte)
      2. Répartition sessions/semaine (courbes + barres)
      3. Score par semaine (barres groupées)

    Tableau récap : score total, nb semaines résolues, durée, hyperparamètres.

    instance_a / instance_b : sous-chaîne du chemin d'instance
                              (ex: "inge", "sorbonne_large")
    """
    ea_list = _load_semester_entries(logfile, instance_a)
    eb_list = _load_semester_entries(logfile, instance_b)

    if not ea_list:
        print(f"Aucun run semestre pour '{instance_a}'.")
        return
    if not eb_list:
        print(f"Aucun run semestre pour '{instance_b}'.")
        return

    ea, eb = ea_list[-1], eb_list[-1]  # dernier run de chaque

    def _parse(e):
        weeks   = e.get("weeks") or []
        rpart   = {int(k): v for k, v in (e.get("repartition") or {}).items()}
        nb_w    = e.get("nb_weeks") or len(weeks)
        s_map   = {w["week"]: w["status"] for w in weeks}
        sc_map  = {w["week"]: w["score"]  for w in weeks}
        return nb_w, rpart, s_map, sc_map

    nb_a, rep_a, st_a, sc_a = _parse(ea)
    nb_b, rep_b, st_b, sc_b = _parse(eb)
    nb_w = max(nb_a, nb_b)
    week_ids = list(range(nb_w))

    lbl_a = _inst_label(ea.get("input", "A"))
    lbl_b = _inst_label(eb.get("input", "B"))

    # ── Tableau récap ─────────────────────────────────────────────────────
    def _summary(e, nb_w, s_map):
        solved = sum(1 for w in range(nb_w) if s_map.get(w) in ("OPTIMAL","FEASIBLE"))
        opt    = sum(1 for w in range(nb_w) if s_map.get(w) == "OPTIMAL")
        dur    = e.get("duration_sec", 0)
        def _s(v): return str(v) if v is not None else "—"
        return {
            "score":                          e.get("score"),
            "resolved":                       f"{solved}/{nb_w}",
            "optimal":                        f"{opt}/{nb_w}",
            "duree":                          f"{int(dur//60)}m{dur%60:.0f}s",
            "num_workers":                    _s(e.get("num_workers")),
            "balance_weight":                 _s(e.get("balance_weight")),
            "ordering_weight":                _s(e.get("ordering_weight")),
            "order_penalty":                  _s(e.get("order_penalty")),
            "max_sessions_per_group_per_week":_s(e.get("max_sessions_per_group_per_week")),
            "t_week_solve (s)":               _s(e.get("timeout_week_solve")),
            "t_per_week (s)":                 _s(e.get("timeout_per_week")),
            "week_solve_status":              _s(e.get("week_solve_status")),
            "week_solve_objective":           _s(e.get("week_solve_objective")),
            "timestamp":                      e.get("timestamp", ""),
        }

    sa, sb = _summary(ea, nb_a, st_a), _summary(eb, nb_b, st_b)
    print(f"\n{'':35} {'':>40}  {'':>40}")
    print(f"{'':35} {lbl_a:>40}  {lbl_b:>40}")
    print("─" * 120)
    for key in ["score","resolved","optimal","duree","num_workers",
                "balance_weight","ordering_weight","order_penalty",
                "max_sessions_per_group_per_week",
                "t_week_solve (s)","t_per_week (s)",
                "week_solve_status","week_solve_objective","timestamp"]:
        print(f"  {key:<33} {str(sa[key]):>40}  {str(sb[key]):>40}")

    # ── Graphes ───────────────────────────────────────────────────────────
    fig, axes = plt.subplots(1, 3, figsize=(18, 6))

    # ── 1. Statuts par semaine (barres empilées) ──────────────────────────
    ax = axes[0]
    x     = np.arange(nb_w)
    width = 0.35
    for offset, (s_map, label, color_alpha) in enumerate([
        (st_a, lbl_a, 1.0), (st_b, lbl_b, 0.6)
    ]):
        bottoms = np.zeros(nb_w)
        for status in STATUS_ORDER:
            vals = np.array([1 if s_map.get(w) == status else 0 for w in week_ids], dtype=float)
            c = STATUS_COLORS[status]
            ax.bar(x + (offset - 0.5) * width, vals, width,
                   bottom=bottoms, color=c, alpha=color_alpha,
                   label=f"{label} {status}" if vals.any() else "_nolegend_",
                   edgecolor="white", linewidth=0.3)
            bottoms += vals
    ax.set_xlabel("Semaine")
    ax.set_ylabel("Statut (1 = ce statut)")
    ax.set_title("Statut par semaine")
    ax.set_xticks(week_ids)
    ax.set_xticklabels([str(w) for w in week_ids], fontsize=7)
    ax.legend(fontsize=7, ncol=2)
    ax.grid(axis="y", alpha=0.3)

    # ── 2. Répartition sessions/semaine ──────────────────────────────────
    ax = axes[1]
    rep_a_vals = [rep_a.get(w, 0) for w in week_ids]
    rep_b_vals = [rep_b.get(w, 0) for w in week_ids]
    ax.bar(x - width/2, rep_a_vals, width, label=lbl_a, color="#3498db", alpha=0.85, edgecolor="white")
    ax.bar(x + width/2, rep_b_vals, width, label=lbl_b, color="#e67e22", alpha=0.85, edgecolor="white")
    if any(v > 0 for v in rep_a_vals):
        ax.axhline(np.mean([v for v in rep_a_vals if v > 0]),
                   color="#3498db", linestyle="--", lw=1.2, alpha=0.7, label=f"moy {lbl_a}")
    if any(v > 0 for v in rep_b_vals):
        ax.axhline(np.mean([v for v in rep_b_vals if v > 0]),
                   color="#e67e22", linestyle="--", lw=1.2, alpha=0.7, label=f"moy {lbl_b}")
    ax.set_xlabel("Semaine")
    ax.set_ylabel("Nb sessions")
    ax.set_title("Répartition sessions/semaine")
    ax.set_xticks(week_ids)
    ax.set_xticklabels([str(w) for w in week_ids], fontsize=7)
    ax.legend(fontsize=8)
    ax.grid(axis="y", alpha=0.3)

    # ── 3. Score par semaine ──────────────────────────────────────────────
    ax = axes[2]
    sc_a_vals = [sc_a.get(w) for w in week_ids]
    sc_b_vals = [sc_b.get(w) for w in week_ids]
    for offset, (sc_vals, label, color) in enumerate([
        (sc_a_vals, lbl_a, "#3498db"), (sc_b_vals, lbl_b, "#e67e22")
    ]):
        valid = [(w, s) for w, s in zip(week_ids, sc_vals) if s is not None]
        if valid:
            ws, ss = zip(*valid)
            ax.bar(np.array(ws) + (offset - 0.5) * width, ss, width,
                   label=label, color=color, alpha=0.85, edgecolor="white")
    ax.set_xlabel("Semaine")
    ax.set_ylabel("Score (à minimiser, plus bas = mieux)")
    ax.set_title("Score par semaine")
    ax.set_xticks(week_ids)
    ax.set_xticklabels([str(w) for w in week_ids], fontsize=7)
    ax.legend(fontsize=8)
    ax.grid(axis="y", alpha=0.3)

    plt.suptitle(f"Comparaison semestre : {lbl_a}  vs  {lbl_b}", fontsize=13, y=1.01)
    plt.tight_layout()
    plt.show()

    return {"a": ea, "b": eb}


# ─── Appels (décommenter selon besoin) ───────────────────────────────────────
# explain_runtime()
# score_by_constraints()
# runtime_by_constraints()
# runtime_by_instance()
# score_vs_time_colored()
# pareto_plot()
# timeout_analysis()
# constraint_marginal_cost()
# constraint_marginal_cost(instance_name="real-univ")
# instance_complexity_vs_runtime()
# nb_days = 3
# nb_slots_per_day = 10
# lunch_slots = [2, 3, 4]
# config = [
#     {
#         "name": "LongLunch",
#         "is_hard": False,
#         "is_active": True,
#         "weight": 3,
#         "lunch_slots": lunch_slots,
#         "nb_slots_per_day": nb_slots_per_day
#     },
#     {
#         "name": "NoGap",
#         "is_hard": False,
#         "is_active": True,
#         "weight": 1,
#         "lunch_slots": lunch_slots,
#         "nb_slots_per_day": nb_slots_per_day
#     },
#     {
#         "name": "NoLateDay",
#         "is_hard": False,
#         "is_active": True,
#         "weight": 2,
#         "lunch_slots": lunch_slots,
#         "nb_slots_per_day": nb_slots_per_day
#     },
#     {
#         "name": "LongLunchTeacher",
#         "is_hard": False,
#         "is_active": True,
#         "weight": 3,
#         "lunch_slots": lunch_slots,
#         "nb_slots_per_day": nb_slots_per_day
#     },
#     {
#         "name": "NoLateDayTeacher",
#         "is_hard": False,
#         "is_active": True,
#         "weight": 2,
#         "lunch_slots": lunch_slots,
#         "nb_slots_per_day": nb_slots_per_day
#     }
# ]
# score_vs_runtime(instance="real-univ",config=config)