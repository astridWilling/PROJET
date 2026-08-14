import os, json, datetime
from typing import List, Optional
from basics import *

# ===========================================================================
# LOGGING PERTURBATIONS
# ===========================================================================

_LOG_DEFAULT_PERTURB = os.path.join(HERE, "Log", "log_perturbations.jsonl")

_STATUS_RANK = {"OPTIMAL": 0, "FEASIBLE": 1, "GREEDY": 2, "INFEASIBLE": 3, "UNKNOWN": 4}

def _overall_status(statuses: list) -> str:
    """Retourne le statut le moins bon de la cascade (OPTIMAL > FEASIBLE > GREEDY > INFEASIBLE > UNKNOWN)."""
    if not statuses:
        return "UNKNOWN"
    return max(statuses, key=lambda s: _STATUS_RANK.get(s, 4))


def log_perturbation(
    input_edt:           str,
    output_edt:          str,
    perturbations:       list,
    total_attempted:     int,
    cancelled:           List[ScheduleItem],
    courses:             List,
    duration:            float,
    nb_days:             int,
    lunch_debut_min:     int,
    lunch_fin_min:       int,
    solver_statuses:     Optional[List[str]] = None,
    scores_base:         Optional[dict]      = None,
    scores_perturb:      Optional[dict]      = None,
    scores_delta:        Optional[dict]      = None,
    experiment_id:       Optional[str]       = None,
    deadline_violations: Optional[List]      = None,
    deadline_days:       Optional[dict]      = None,
    rescheduled_moves:   Optional[List[dict]] = None,
    added_sessions:      Optional[List[dict]] = None,
    not_added_sessions:  Optional[List[dict]] = None,
    removed_sessions:    Optional[List[dict]] = None,
    not_removed_sessions: Optional[List[dict]] = None,
    current_day:         Optional[int]       = None,
    logfile:             str                 = _LOG_DEFAULT_PERTURB,
):
    """
    Écrit une entrée JSONL pour un run de perturbation.
    Compatible avec le même fichier de log que le solver (run_type='perturbation').

    Champs communs avec le solver : timestamp, input, nb_days, output,
        experiment_id, duration_sec, duration_pretty, nb_unplaced.
    Champs spécifiques : perturbations, total_attempted, cancelled_details,
        soft_scorers, lunch_debut, lunch_fin, status.
    """
    os.makedirs(os.path.dirname(logfile), exist_ok=True)

    course_map = {c.id: c for c in courses}
    course_map.update({str(c.id): c for c in courses})

    cancelled_details = []
    for item in cancelled:
        cobj = course_map.get(base_course_id(item.course))
        cancelled_details.append({
            "course_name":  cobj.name       if cobj else str(item.course),
            "course_types": cobj.room_types if cobj else [],
            "group":        [g.id for g in item.group],
            "day":          item.day,
            "heure_debut":  item.heure_debut,
            "heure_fin":    item.heure_fin,
        })

    deadline_violation_details = []
    for item in (deadline_violations or []):
        cobj = course_map.get(base_course_id(item.course))
        dl   = (deadline_days or {}).get(base_course_id(item.course))
        deadline_violation_details.append({
            "course_name": cobj.name if cobj else str(item.course),
            "group":       [g.id for g in item.group],
            "day_placed":  item.day,
            "heure_debut": item.heure_debut,
            "heure_fin":   item.heure_fin,
            "deadline_day": dl,
        })

    nb_cancelled   = len(cancelled)
    statuses       = solver_statuses or []
    overall        = _overall_status(statuses)

    pretty_duration = f"{int(duration // 60)}'{duration % 60:.2f}\""

    perturb_summary = []
    for p in perturbations:
        if p["type"] == 1:
            perturb_summary.append({"type": "teacher_absent",
                                    "teacher_id": p["teacher_id"],
                                    "intervals": p["intervals"]})
        elif p["type"] == 2:
            perturb_summary.append({"type": "room_unavailable",
                                    "room": p["room"],
                                    "intervals": p["intervals"]})
        elif p["type"] == 3:
            perturb_summary.append({"type": "free_slot",
                                    "groups": p["groups"],
                                    "intervals": p["intervals"]})
        elif p["type"] == 4:
            perturb_summary.append({"type":                "teacher_replacement",
                                    "teacher_id":          p.get("teacher_id"),
                                    "course_name":         p.get("course_name"),
                                    "target_groups":       p.get("target_groups"),
                                    "target_session_type": p.get("target_session_type"),
                                    "intervals":           p.get("intervals")})
        elif p["type"] == 5:
            to_move  = p["to_move"]
            placed   = p.get("placed_item")
            cobj     = course_map.get(base_course_id(to_move.course))
            entry5   = {
                "type":               "move",
                "course_name":        cobj.name if cobj else str(to_move.course),
                "group":              [g.id for g in to_move.group],
                "origin_day":         to_move.day,
                "origin_heure_debut": to_move.heure_debut,
                "origin_heure_fin":   to_move.heure_fin,
                "origin_room":        to_move.room,
                "target_day":         p["target_day"],
                "requested_heure_debut": p.get("heure_debut"),
                "placed_as_requested":   p.get("placed_as_requested"),
            }
            if placed:
                entry5["placed_day"]        = placed.day
                entry5["placed_heure_debut"] = placed.heure_debut
                entry5["placed_heure_fin"]   = placed.heure_fin
                entry5["placed_room"]        = placed.room
            else:
                entry5["placed_day"] = None
            perturb_summary.append(entry5)

        elif p["type"] == 8:
            perturb_summary.append({
                "type":    "add_session",
                "to_add":  [
                    {
                        "course":       tup[0].name if hasattr(tup[0], "name") else str(tup[0]),
                        "teacher":      tup[1].id   if hasattr(tup[1], "id")   else str(tup[1]),
                        "group":        [g.id for g in tup[2]] if isinstance(tup[2], list) else [tup[2].id],
                        "session_type": tup[3],
                        "duration":     tup[4],
                        "week":         tup[5],
                        "day":          tup[6],
                        "room":         tup[7].name if tup[7] else None,
                        "heure_debut":  tup[8],
                    }
                    for tup in p.get("to_add", [])
                ],
            })

        elif p["type"] == 9:
            perturb_summary.append({
                "type":      "remove_session",
                "to_remove": [
                    {
                        "course_name":  (course_map.get(base_course_id(it.course)) or
                                         type("_", (), {"name": str(it.course)})()).name,
                        "group":        [g.id for g in it.group],
                        "session_type": it.session_type,
                        "day":          it.day,
                        "heure_debut":  it.heure_debut,
                        "heure_fin":    it.heure_fin,
                    }
                    for it in p.get("to_remove", [])
                ],
            })

        elif p["type"] == 6:
            perm1  = p["perm1"]
            perm2  = p["perm2"]
            c1_obj = course_map.get(base_course_id(perm1.course))
            c2_obj = course_map.get(base_course_id(perm2.course))
            placed = p.get("placed_items") or []
            entry6 = {
                "type":            "permutation",
                "keep_room":       p.get("keep_room", False),
                "move_courses":    p.get("move_courses", True),
                "course1": {
                    "name":        c1_obj.name if c1_obj else str(perm1.course),
                    "group":       [g.id for g in perm1.group],
                    "origin_day":  perm1.day,
                    "origin_hd":   perm1.heure_debut,
                    "origin_hf":   perm1.heure_fin,
                    "origin_room": perm1.room,
                    "placed":      {"day": placed[0].day, "hd": placed[0].heure_debut,
                                    "hf": placed[0].heure_fin, "room": placed[0].room}
                                   if len(placed) > 0 and placed[0] else None,
                },
                "course2": {
                    "name":        c2_obj.name if c2_obj else str(perm2.course),
                    "group":       [g.id for g in perm2.group],
                    "origin_day":  perm2.day,
                    "origin_hd":   perm2.heure_debut,
                    "origin_hf":   perm2.heure_fin,
                    "origin_room": perm2.room,
                    "placed":      {"day": placed[1].day, "hd": placed[1].heure_debut,
                                    "hf": placed[1].heure_fin, "room": placed[1].room}
                                   if len(placed) > 1 and placed[1] else None,
                },
            }
            perturb_summary.append(entry6)

    entry = {
        "run_type":         "perturbation",
        "timestamp":        datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "experiment_id":    experiment_id,
        "input":            input_edt,
        "output":           output_edt,
        "nb_days":          nb_days,
        "lunch_debut":      min_to_hm(lunch_debut_min),
        "lunch_fin":        min_to_hm(lunch_fin_min),
        "perturbations":    perturb_summary,
        "total_attempted":   total_attempted,
        "nb_unplaced":       nb_cancelled,
        "solver_statuses":   statuses,
        "overall_status":    overall,
        "scores_base":       scores_base   or {},
        "scores_perturb":    scores_perturb or {},
        "scores_delta":      scores_delta   or {},
        "cancelled_details":           cancelled_details,
        "nb_deadline_violations":      len(deadline_violation_details),
        "deadline_violation_details":  deadline_violation_details,
        "rescheduled_moves":           rescheduled_moves or [],
        "added_sessions":              added_sessions       or [],
        "not_added_sessions":          not_added_sessions   or [],
        "removed_sessions":            removed_sessions     or [],
        "not_removed_sessions":        not_removed_sessions or [],
        "current_day":                 current_day,
        "duration_sec":     round(duration, 3),
        "duration_pretty":  pretty_duration,
    }

    with open(logfile, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    print(f"[log] Entrée écrite dans {logfile}")


# ===========================================================================
# SAUVEGARDE / CHARGEMENT EDT
# ===========================================================================

def save_edt(schedule: List[ScheduleItem], name: str, folder: str = None) -> str:
    folder = folder or EDT_DIR
    os.makedirs(folder, exist_ok=True)
    filepath = os.path.join(folder, name + ".json")
    data = [
        {
            "course":      item.course,
            "group":       [{"id": g.id, "headcount": g.headcount} for g in item.group],
            "teacher": {
                "id":      item.teacher.id,
                "name":    item.teacher.name,
                "courses": list(item.teacher.courses),
            },
            "day":         item.day,
            "heure_debut": item.heure_debut,
            "heure_fin":   item.heure_fin,
            "room":        item.room,
            "building":    item.building,
            "session_type": item.session_type,
        }
        for item in schedule
    ]
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"EDT sauvegardé : {filepath}")
    return filepath


def load_edt(name: str, groups_map: dict = None) -> List[ScheduleItem]:
    filepath = os.path.join(EDT_DIR, name + ".json")
    with open(filepath, encoding="utf-8") as f:
        data = json.load(f)

    def _load_group(gdata):
        if groups_map and gdata["id"] in groups_map:
            return groups_map[gdata["id"]]
        return Group(id=gdata["id"], headcount=gdata.get("headcount", 0))

    schedule = [
        ScheduleItem(
            course=      item["course"],
            group=       [_load_group(g) for g in item["group"]],
            teacher=     Teacher(
                id=      item["teacher"]["id"],
                name=    item["teacher"]["name"],
                courses= item["teacher"]["courses"],
            ),
            day=         item["day"],
            heure_debut= item["heure_debut"],
            heure_fin=   item["heure_fin"],
            room=         item["room"],
            building=     item.get("building"),
            session_type= item.get("session_type"),
        )
        for item in data
    ]
    print(f"EDT chargé : {filepath}  ({len(schedule)} sessions)")
    return schedule


# ===========================================================================
# CHARGEEMNT DES DONNÉES D'ENTRÉE
# ===========================================================================

def load_input(filepath: str):
    with open(filepath, encoding="utf-8") as f:
        data = json.load(f)
    rooms = [
        Room(r["name"], r["capacity"], r["room_types"], r.get("bat", "default"))
        for r in data["rooms"]
    ]
    teachers = {t["id"]: Teacher(t["id"], t["name"], []) for t in data["teachers"]}
    group_size = {g["id"]: g["size"] for g in data["groups"]}
    courses = [
        Course(
            id=c["id"], name=c["name"], teacher=teachers[c["teacher"]],
            group=c["group"], headcount=group_size[c["group"]],
            room_types=c["room_types"], slots_per_week=c["slots_per_week"],
            session_room_types=c.get("session_room_types"),
            ordering_preference=c.get("ordering_preference"),
        )
        for c in data["courses"]
    ]
    sessions_map = {c["id"]: c["sessions"] for c in data["courses"] if "sessions" in c}
    return courses, rooms, list(teachers.values()), None, sessions_map



# ===========================================================================
# AFFICHAGE HTML
# ===========================================================================

def affichage_html_complet(schedule, nb_days, courses, rooms,
                           filename="edt.html",
                           lunch_debut_min=735, lunch_fin_min=840,
                           room_unavailable_intervals=None,
                           teacher_unavail_intervals=None,
                           group_unavail_intervals=None,
                           cancelled_items=None,
                           deadline_violations=None,
                           deadline_days=None,
                           added_items=None,
                           not_added_items=None,
                           removed_items=None,
                           not_removed_items=None,
                           folder: str = None):
    """
    Affichage proportionnel au temps : 1 pixel = PX_PER_MIN minutes.
    Chaque cours est un <div> positionné en absolu dans sa colonne-jour :
        top    = (heure_debut - DAY_START) * PX_PER_MIN
        height = (heure_fin   - heure_debut) * PX_PER_MIN
    Les trous apparaissent naturellement comme de l'espace vide.
    """
    folder = folder or EDT_DIR
    os.makedirs(folder, exist_ok=True)
    filepath = os.path.join(folder, filename)

    PX_PER_MIN = 1.0
    DAY_START  = (min(hm(item.heure_debut) for item in schedule) // 60) * 60
    DAY_END    = ((max(hm(item.heure_fin)  for item in schedule) + 59) // 60) * 60
    TOTAL_PX   = int((DAY_END - DAY_START) * PX_PER_MIN)

    def px_top(heure):
        return int((hm(heure) - DAY_START) * PX_PER_MIN)

    def px_height(hdebut, hfin):
        return max(int((hm(hfin) - hm(hdebut)) * PX_PER_MIN), 4)

    days_names = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi"]
    nb_weeks   = max(1, nb_days // 5)
    teachers    = sorted(set(item.teacher.id for item in schedule))
    teacher_map = {item.teacher.id: item.teacher for item in schedule}

    # Construire la relation parent → enfants depuis les Group objects du planning
    _all_gobj = {g.id: g for item in schedule for g in item.group}
    _children: dict = defaultdict(list)
    for gid, g in _all_gobj.items():
        if g.parent:
            _children[g.parent.id].append(gid)

    def _display_ids(group: "Group") -> List[str]:
        """IDs sous lesquels cet item doit apparaître : ancêtres + descendants."""
        ids = set(group.ancestors())
        stack = [group.id]
        while stack:
            curr = stack.pop()
            for child_id in _children.get(curr, []):
                ids.add(child_id)
                stack.append(child_id)
        return list(ids)

    for gid, g in list(_all_gobj.items()):
        if g.parent and g.parent.subgroup_ids:
            par_id = g.parent.id
            for sib_id in g.parent.subgroup_ids:
                if sib_id not in _children[par_id]:
                    _children[par_id].append(sib_id)
    
    grp_items = defaultdict(lambda: defaultdict(list))
    tch_items = defaultdict(lambda: defaultdict(list))
    for item in schedule:
        seen = set()
        for g in item.group:
            for gid in _display_ids(g):
                if gid not in seen:
                    grp_items[gid][item.day].append(item)
                    seen.add(gid)
        tch_items[item.teacher.id][item.day].append(item)

    # Afficher uniquement les groupes feuilles (pas d'enfants) — les groupes parents
    # sont masqués car leurs cours sont distribués dans les onglets sous-groupes
    groups = sorted(gid for gid in grp_items if not _children.get(gid))

    lunch_top    = int((lunch_debut_min - DAY_START) * PX_PER_MIN)
    lunch_height = int((lunch_fin_min   - lunch_debut_min) * PX_PER_MIN)
    # Une ligne toutes les heures
    hour_lines = []

    for minute in range(DAY_START, DAY_END + 1, 60):
        h = minute // 60
        m = minute % 60

        label = f"{h:02d}:{m:02d}"
        pos = int((minute - DAY_START) * PX_PER_MIN)

        hour_lines.append((label, pos))

    css = f"""
body {{ font-family: Arial; font-size: 12px; margin: 0; padding: 10px; }}
h1, h2 {{ margin: 8px 20px; }}
.tab {{ display: none; }} .tab.active {{ display: block; }}
.tab-buttons {{ margin: 8px 20px; }}
.tab-buttons button {{ margin: 4px; padding: 6px 12px; cursor: pointer;
                       border-radius: 4px; border: 1px solid #aaa; background: #f5f5f5; }}
.tab-buttons button:hover {{ background: #ddd; }}
.tab-buttons button.tab-active {{ background: #3a6ea8; color: #fff; border-color: #2a5088; font-weight: bold; }}
.legend {{ display: flex; flex-wrap: wrap; gap: 12px; margin: 6px 20px 10px; font-size: 11px; align-items: center; }}
.legend-item {{ display: flex; align-items: center; gap: 5px; }}
.legend-swatch {{ width: 18px; height: 18px; border-radius: 3px; flex-shrink: 0; }}
.week-wrap {{ margin: 10px 20px; }}
.week-header {{ display: flex; margin-left: 60px; }}
.week-header-day {{ flex: 1; text-align: center; font-weight: bold;
                    border: 1px solid #bbb; padding: 4px; background: #ddd; border-bottom: none; }}
.week-body {{ display: flex; height: {TOTAL_PX}px; border: 1px solid #bbb; }}
.time-col {{ width: 58px; flex-shrink: 0; position: relative;
             border-right: 2px solid #999; box-sizing: border-box; }}
.hour-label {{ position: absolute; right: 4px; font-size: 10px; color: #555;
               transform: translateY(-50%); white-space: nowrap; }}
.day-col {{ flex: 1; position: relative; border-right: 1px solid #ccc; box-sizing: border-box; }}
.day-col:last-child {{ border-right: none; }}
.lunch-zone {{ position: absolute; left: 0; right: 0;
               background: rgba(255,243,205,0.55); pointer-events: none; }}
.hour-line {{ position: absolute; left: 0; right: 0;
              border-top: 1px solid #e0e0e0; pointer-events: none; }}
.course-block {{ position: absolute; left: 2px; right: 2px; border-radius: 4px;
                 font-size: 10px; overflow: hidden; display: flex; flex-direction: column;
                 justify-content: center; align-items: center; text-align: center;
                 border: 1px solid rgba(0,0,0,0.2); box-sizing: border-box; padding: 2px; }}
.course-block:hover {{ filter: brightness(0.92); z-index: 10; }}
.course-block b {{ font-size: 11px; }}
.sub {{ font-size: 9px; color: #333; }}
.stype {{ display: inline-block; font-size: 8px; font-weight: bold; padding: 0 3px;
          border-radius: 3px; margin-left: 3px; background: rgba(0,0,0,0.15);
          color: #fff; vertical-align: middle; letter-spacing: 0.5px; }}
.conflict {{ border: 2px solid #c00 !important; box-shadow: 0 0 4px rgba(200,0,0,0.6); }}
.conflict-label {{ font-size: 9px; color: #c00; font-weight: bold; }}
.exam-block {{ background: #8b0000 !important; color: #fff !important; border: 2px solid #500 !important; }}
.exam-block .sub {{ color: #ffcccc !important; }}
.exam-block b {{ color: #fff !important; }}
.deadline-native {{ border: 3px solid #1a6fcf !important; box-shadow: 0 0 6px rgba(26,111,207,0.7); }}
.deadline-perturbed {{ border: 3px solid #d06000 !important; box-shadow: 0 0 6px rgba(208,96,0,0.7); }}
.added-block {{ border: 3px solid #1a7a3c !important; box-shadow: 0 0 6px rgba(26,122,60,0.7); }}
.alert-banner {{ position: sticky; top: 0; z-index: 100; background: #c00; color: #fff;
                 font-size: 15px; font-weight: bold; padding: 10px 20px;
                 display: flex; align-items: center; gap: 12px; }}
.alert-banner a {{ color: #fff; text-decoration: underline; cursor: pointer; }}
.alert-banner.deadline {{ background: #d06000; }}
.alert-banner.added {{ background: #1a7a3c; }}
.alert-banner.not-added {{ background: #6a3a8a; }}
.alert-banner.removed {{ background: #1a7a3c; }}
.alert-banner.not-removed {{ background: #c00; }}
.week-bar {{ position: sticky; top: 0; z-index: 90; background: #fff;
             border-bottom: 2px solid #bbb; padding: 6px 20px;
             display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }}
.week-bar span {{ font-weight: bold; margin-right: 8px; color: #444; }}
.week-btn {{ padding: 4px 10px; cursor: pointer; border-radius: 4px;
             border: 1px solid #aaa; background: #f5f5f5; font-size: 12px; }}
.week-btn:hover {{ background: #ddd; }}
.week-btn.wk-active {{ background: #3a6ea8; color: #fff; border-color: #2a5088; font-weight: bold; }}
.week-pane {{ display: none; }}
.week-pane.active {{ display: block; }}
.cancelled-table {{ border-collapse: collapse; margin: 10px 20px; width: calc(100% - 40px); }}
.cancelled-table th {{ background: #c00; color: #fff; padding: 8px 12px; text-align: left; }}
.cancelled-table td {{ padding: 7px 12px; border-bottom: 1px solid #eee; }}
.cancelled-table tr:hover td {{ background: #fff0f0; }}
.deadline-table {{ border-collapse: collapse; margin: 10px 20px; width: calc(100% - 40px); }}
.deadline-table th {{ background: #d06000; color: #fff; padding: 8px 12px; text-align: left; }}
.deadline-table td {{ padding: 7px 12px; border-bottom: 1px solid #eee; }}
.deadline-table tr:hover td {{ background: #fff8f0; }}
.unavail-block {{ position: absolute; left: 2px; right: 2px; border-radius: 4px;
                  box-sizing: border-box;
                  background: repeating-linear-gradient(
                    45deg, rgba(200,50,50,0.18), rgba(200,50,50,0.18) 4px,
                    rgba(200,50,50,0.05) 4px, rgba(200,50,50,0.05) 10px);
                  border: 1px solid rgba(180,40,40,0.4);
                  display: flex; align-items: center; justify-content: center;
                  font-size: 9px; color: #a00; font-weight: bold; pointer-events: none; }}
"""

    js = """
var _currentWeek = 0;

function showWeek(w){
    _currentWeek = w;
    document.querySelectorAll(".week-btn").forEach(function(b){
        b.classList.toggle("wk-active", parseInt(b.dataset.week) === w);
    });
    document.querySelectorAll(".week-pane").forEach(function(p){
        p.classList.toggle("active", parseInt(p.dataset.week) === w);
    });
}

function _setActiveBtn(btn){
    if(!btn) return;
    var container = btn.closest(".tab-buttons");
    if(container) container.querySelectorAll("button").forEach(b=>b.classList.remove("tab-active"));
    btn.classList.add("tab-active");
}

function showTab(id, btn){
    var roots=["groups","teachers","rooms","cancelled","deadlines","added","not-added","removed","not-removed"];
    if(roots.includes(id)){
        roots.forEach(x=>{var el=document.getElementById(x);if(el)el.classList.remove("active");});
        document.getElementById(id).classList.add("active");
        _setActiveBtn(btn||null);
        if(id==="groups"||id==="teachers"||id==="rooms"){
            var pfx=id==="groups"?"group_":id==="teachers"?"teacher_":"room_";
            var first=document.querySelector("[id^='"+pfx+"']");
            if(first){
                document.querySelectorAll("[id^='"+pfx+"']").forEach(x=>x.classList.remove("active"));
                first.classList.add("active");
                var firstBtn=first.closest(".tab")==null?null:document.querySelector(".tab-buttons button[data-sub='"+first.id+"']");
                _setActiveBtn(firstBtn);
            }
        }
    } else if(id.startsWith("group_")||id.startsWith("teacher_")||id.startsWith("room_")){
        var pfx2=id.startsWith("group_")?"group_":id.startsWith("teacher_")?"teacher_":"room_";
        document.querySelectorAll("[id^='"+pfx2+"']").forEach(x=>x.classList.remove("active"));
        document.getElementById(id).classList.add("active");
        _setActiveBtn(btn||null);
    }
    showWeek(_currentWeek);
}
"""

    def _assign_lanes(day_items):
        """
        Assigne une lane (colonne) et un total de lanes à chaque item du jour
        pour que les cours qui se chevauchent s'affichent côte à côte.
        Retourne dict: id(item) -> (lane_index, nb_lanes)
        """
        # Trier par heure de début
        items = sorted(day_items, key=lambda x: hm(x.heure_debut))
        # lanes[k] = heure de fin du dernier item assigné à la lane k
        lane_ends = []
        item_lane = {}  # id(item) -> lane_index

        for item in items:
            t1, t2 = hm(item.heure_debut), hm(item.heure_fin)
            assigned = None
            for k, end in enumerate(lane_ends):
                if t1 >= end:
                    assigned = k
                    lane_ends[k] = t2
                    break
            if assigned is None:
                assigned = len(lane_ends)
                lane_ends.append(t2)
            item_lane[id(item)] = assigned

        # Calculer le nb de lanes nécessaires pour chaque item :
        # c'est le max de lanes actives pendant son intervalle
        result = {}
        for item in items:
            t1, t2 = hm(item.heure_debut), hm(item.heure_fin)
            # compter combien d'items chevauchent cet item (lui inclus)
            nb = sum(
                1 for other in items
                if hm(other.heure_debut) < t2 and t1 < hm(other.heure_fin)
            )
            result[id(item)] = (item_lane[id(item)], nb)
        return result

    _deadline_violations_set = set(
        (it.course, it.day, it.heure_debut, it.room)
        for it in (deadline_violations or [])
    )
    _added_set = set(
        (it.course, it.day, it.heure_debut, it.room)
        for it in (added_items or [])
    )

    def render_week(items_by_day, detail_fn, unavail_by_day=None, week=0, _deadline_days=None, _buffer=DEADLINE_BUFFER_DAYS):
        """
        unavail_by_day   : dict[abs_day -> List[(heure_debut, heure_fin)]]
        week             : index de semaine 0-based
        _deadline_days   : dict {course_id: jour_limite} pour détecter violations natives
        """
        days_range = range(week * 5, week * 5 + 5)
        lanes_by_day = {d: _assign_lanes(items_by_day.get(d, [])) for d in days_range}
        out = "<div class='week-wrap'>"
        out += "<div class='week-header'>"
        for dn in days_names:
            out += f"<div class='week-header-day'>{dn}</div>"
        out += "</div><div class='week-body'>"

        # Axe horaire
        out += "<div class='time-col'>"
        out += f"<div class='lunch-zone' style='top:{lunch_top}px;height:{lunch_height}px'></div>"
        for label, tp in hour_lines:
            out += f"<div class='hour-label' style='top:{tp}px'>{label}</div>"
        out += "</div>"

        # Colonnes jour (jours absolus de cette semaine)
        for d in days_range:
            out += "<div class='day-col'>"
            out += f"<div class='lunch-zone' style='top:{lunch_top}px;height:{lunch_height}px'></div>"
            for _, tp in hour_lines:
                out += f"<div class='hour-line' style='top:{tp}px'></div>"
            # Blocs indisponibilité (en dessous des cours)
            if unavail_by_day:
                for (hd, hf) in unavail_by_day.get(d, []):
                    tp = px_top(hd)
                    hp = max(px_height(hd, hf), 4)
                    out += (
                        f"<div class='unavail-block' style='top:{tp}px;height:{hp}px'>"
                        f"Indispo {hd}–{hf}</div>"
                    )
            for item in items_by_day.get(d, []):
                tp = px_top(item.heure_debut)
                hp = px_height(item.heure_debut, item.heure_fin)
                if tp < 0 or tp > TOTAL_PX:
                    continue
                color = f"hsl({(item.course * 40) % 360},65%,82%)"
                cobj  = next((c for c in courses if c.id == item.course), None)
                cname = cobj.name if cobj else f"C{item.course}"

                lane_info = lanes_by_day.get(d, {}).get(id(item), (0, 1))
                lane_idx, nb_lanes = lane_info
                is_conflict = nb_lanes > 1
                is_exam     = item.session_type == "Exam"
                _cid = base_course_id(item.course)
                _dl  = (_deadline_days or {}).get(_cid) if not is_exam and _deadline_days else None
                if _dl is None and _deadline_days:
                    try: _dl = _deadline_days.get(int(_cid))
                    except (ValueError, TypeError): pass
                is_native_deadline = _dl is not None and item.day > _dl - _buffer
                is_perturbed_deadline = (
                    not is_exam
                    and (item.course, item.day, item.heure_debut, item.room) in _deadline_violations_set
                )
                is_added = (item.course, item.day, item.heure_debut, item.room) in _added_set
                extra_cls = ""
                if is_conflict:            extra_cls += " conflict"
                if is_exam:                extra_cls += " exam-block"
                if is_perturbed_deadline:  extra_cls += " deadline-perturbed"
                elif is_native_deadline:   extra_cls += " deadline-native"
                if is_added:               extra_cls += " added-block"
                conflict_lbl = "<span class='conflict-label'>⚠ CONFLIT</span>" if is_conflict else ""

                # Positionnement horizontal côte à côte
                w_pct    = 100 / nb_lanes
                left_pct = lane_idx * w_pct
                style = (f"top:{tp}px;height:{hp}px;background:{color};"
                         f"left:{left_pct:.1f}%;width:{w_pct:.1f}%;right:unset;")

                stype_badge = (f"<span class='stype'>{item.session_type}</span>"
                              if item.session_type else "")
                out += (
                    f"<div class='course-block{extra_cls}' style='{style}'>"
                    f"{conflict_lbl}"
                    f"<b>{cname}</b>{stype_badge}"
                    f"<span class='sub'>{detail_fn(item)}</span>"
                    f"<span class='sub'>{item.heure_debut}–{item.heure_fin}</span>"
                    f"<span class='sub'>{item.room}"
                    f"{f' ({item.building})' if item.building and item.building != '?' else ''}"
                    f"</span>"
                    f"</div>"
                )
            out += "</div>"
        out += "</div></div>"
        return out

    # Index salles → jour → cours
    room_items = defaultdict(lambda: defaultdict(list))
    for item in schedule:
        if item.room != "?":
            room_items[item.room][item.day].append(item)
    all_room_names = {r.name for r in rooms} if rooms else set()
    room_names = sorted(room_items.keys() | all_room_names)

    course_map_html = {c.id: c for c in courses}
    course_map_html.update({str(c.id): c for c in courses})
    cancelled_items    = cancelled_items    or []
    deadline_violations = deadline_violations or []
    added_items        = added_items        or []
    not_added_items    = not_added_items    or []
    removed_items      = removed_items      or []
    not_removed_items  = not_removed_items  or []

    html  = f"<html><head><meta charset='utf-8'><style>{css}</style><script>{js}</script></head><body>"

    if cancelled_items:
        n = len(cancelled_items)
        html += (f"<div class='alert-banner'>⚠ ATTENTION — {n} cours non placé(s) après résolution ! "
                 f"<a onclick=\"showTab('cancelled')\">Voir la liste →</a></div>")
    if deadline_violations:
        n = len(deadline_violations)
        html += (f"<div class='alert-banner deadline'>⚠ ATTENTION — {n} cours placé(s) après leur deadline ! "
                 f"<a onclick=\"showTab('deadlines')\">Voir la liste →</a></div>")
    if added_items:
        n = len(added_items)
        html += (f"<div class='alert-banner added'>✓ {n} session(s) ajoutée(s) avec succès. "
                 f"<a onclick=\"showTab('added')\">Voir la liste →</a></div>")
    if not_added_items:
        n = len(not_added_items)
        html += (f"<div class='alert-banner not-added'>⚠ {n} session(s) non placée(s). "
                 f"<a onclick=\"showTab('not-added')\">Voir la liste →</a></div>")
    if removed_items:
        n = len(removed_items)
        html += (f"<div class='alert-banner removed'>✓ {n} session(s) supprimée(s) avec succès. "
                 f"<a onclick=\"showTab('removed')\">Voir la liste →</a></div>")
    if not_removed_items:
        n = len(not_removed_items)
        html += (f"<div class='alert-banner not-removed'>⚠ {n} session(s) non supprimée(s). "
                 f"<a onclick=\"showTab('not-removed')\">Voir la liste →</a></div>")

    html += "<h1>Emploi du temps</h1>"

    if nb_weeks > 1:
        html += "<div class='week-bar'><span>Semaine :</span>"
        for w in range(nb_weeks):
            active_cls = "wk-active" if w == 0 else ""
            html += (f"<button class='week-btn {active_cls}' data-week='{w}' "
                     f"onclick='showWeek({w})'>S{w+1}</button>")
        html += "</div>"

    html += "<div class='tab-buttons'>"
    html += "<button class='tab-active' onclick=\"showTab('groups',this)\">Groupes</button>"
    html += "<button onclick=\"showTab('teachers',this)\">Profs</button>"
    html += "<button onclick=\"showTab('rooms',this)\">Salles</button>"
    if cancelled_items:
        html += "<button onclick=\"showTab('cancelled',this)\" style='background:#c00;color:#fff;border-color:#a00;font-weight:bold;'>⚠ Non placés</button>"
    if deadline_violations:
        html += "<button onclick=\"showTab('deadlines',this)\" style='background:#d06000;color:#fff;border-color:#a04000;font-weight:bold;'>⚠ Deadlines dépassées</button>"
    if added_items:
        html += "<button onclick=\"showTab('added',this)\" style='background:#1a7a3c;color:#fff;border-color:#155f2f;font-weight:bold;'>✓ Sessions ajoutées</button>"
    if not_added_items:
        html += "<button onclick=\"showTab('not-added',this)\" style='background:#6a3a8a;color:#fff;border-color:#4e2a6a;font-weight:bold;'>⚠ Sessions non placées</button>"
    if removed_items:
        html += "<button onclick=\"showTab('removed',this)\" style='background:#1a7a3c;color:#fff;border-color:#155f2f;font-weight:bold;'>✓ Sessions supprimées</button>"
    if not_removed_items:
        html += "<button onclick=\"showTab('not-removed',this)\" style='background:#c00;color:#fff;border-color:#a00;font-weight:bold;'>⚠ Sessions non supprimées</button>"
    html += "</div>"

    html += "<div class='legend'>"
    html += "<span style='font-weight:bold;color:#555;margin-right:4px;'>Légende :</span>"
    html += "<div class='legend-item'><div class='legend-swatch' style='background:#8b0000;border:2px solid #500;'></div><span>Examen</span></div>"
    html += "<div class='legend-item'><div class='legend-swatch' style='background:rgba(200,200,200,0.3);border:3px solid #1a6fcf;box-shadow:0 0 5px rgba(26,111,207,0.6);'></div><span>Cours après deadline (EDT natif)</span></div>"
    html += "<div class='legend-item'><div class='legend-swatch' style='background:rgba(200,200,200,0.3);border:3px solid #d06000;box-shadow:0 0 5px rgba(208,96,0,0.6);'></div><span>Cours perturbé après deadline</span></div>"
    html += "<div class='legend-item'><div class='legend-swatch' style='background:rgba(200,200,200,0.3);border:2px solid #c00;box-shadow:0 0 4px rgba(200,0,0,0.6);'></div><span>Conflit</span></div>"
    if added_items:
        html += "<div class='legend-item'><div class='legend-swatch' style='background:rgba(200,200,200,0.3);border:3px solid #1a7a3c;box-shadow:0 0 5px rgba(26,122,60,0.6);'></div><span>Session ajoutée</span></div>"
    html += "</div>"

    html += "<div id='groups' class='tab active'><h1>EDT GROUPES</h1>"
    html += "<div class='tab-buttons'>"
    for i, g in enumerate(groups):
        active_cls = " tab-active" if i == 0 else ""
        html += f"<button class='{active_cls}' data-sub='group_{g}' onclick=\"showTab('group_{g}',this)\">{g}</button>"
    html += "</div>"
    for i, g in enumerate(groups):
        active = "active" if i == 0 else ""
        g_unavail = None
        if group_unavail_intervals and g in group_unavail_intervals:
            g_unavail = defaultdict(list)
            for (d, hd, hf) in group_unavail_intervals[g]:
                g_unavail[d].append((hd, hf))
        html += f"<div id='group_{g}' class='tab {active}'><h2>Groupe {g}</h2>"
        def _detail_group(item):
            return item.teacher.name
        for w in range(nb_weeks):
            wp_active = "active" if w == 0 else ""
            html += f"<div class='week-pane {wp_active}' data-week='{w}'>"
            html += render_week(grp_items[g], _detail_group, unavail_by_day=g_unavail, week=w, _deadline_days=deadline_days)
            html += "</div>"
        html += "</div>"
    html += "</div>"

    html += "<div id='teachers' class='tab'><h1>EDT PROFS</h1>"
    html += "<div class='tab-buttons'>"
    for i, tid in enumerate(teachers):
        active_cls = " tab-active" if i == 0 else ""
        html += f"<button class='{active_cls}' data-sub='teacher_{tid}' onclick=\"showTab('teacher_{tid}',this)\">{teacher_map[tid].name}</button>"
    html += "</div>"
    for i, tid in enumerate(teachers):
        active = "active" if i == 0 else ""
        t_name = teacher_map[tid].name
        t_unavail = None
        if teacher_unavail_intervals and tid in teacher_unavail_intervals:
            t_unavail = defaultdict(list)
            for (d, hd, hf) in teacher_unavail_intervals[tid]:
                t_unavail[d].append((hd, hf))
        html += f"<div id='teacher_{tid}' class='tab {active}'><h2>{t_name}</h2>"
        for w in range(nb_weeks):
            wp_active = "active" if w == 0 else ""
            html += f"<div class='week-pane {wp_active}' data-week='{w}'>"
            html += render_week(tch_items[tid],
                                lambda item: ", ".join(g.id for g in item.group),
                                unavail_by_day=t_unavail, week=w, _deadline_days=deadline_days)
            html += "</div>"
        html += "</div>"
    html += "</div>"

    # Salles avec indisponibilités : s'assurer qu'elles apparaissent même sans cours
    if room_unavailable_intervals:
        for rn_unavail in room_unavailable_intervals:
            if rn_unavail not in room_names:
                room_names.append(rn_unavail)

    html += "<div id='rooms' class='tab'><h1>EDT SALLES</h1>"
    html += "<div class='tab-buttons'>"
    for i, rn in enumerate(room_names):
        robj = next((r for r in rooms if r.name == rn), None)
        label = f"{rn} ({robj.capacity}p)" if robj else rn
        active_cls = " tab-active" if i == 0 else ""
        html += f"<button class='{active_cls}' data-sub='room_{rn}' onclick=\"showTab('room_{rn}',this)\">{label}</button>"
    html += "</div>"

    for i, rn in enumerate(room_names):
        active = "active" if i == 0 else ""
        robj   = next((r for r in rooms if r.name == rn), None)
        cap_str = f" — {robj.capacity} places, types: {robj.room_types}" if robj else ""
        # Construire unavail_by_day pour cette salle
        unavail_by_day = None
        if room_unavailable_intervals and rn in room_unavailable_intervals:
            raw_intervals = room_unavailable_intervals[rn]
            if raw_intervals is None:
                # Salle bloquée toute la semaine → couvre toute la journée
                full_hd = min_to_hm(DAY_START)
                full_hf = min_to_hm(DAY_END)
                unavail_by_day = {d: [(full_hd, full_hf)] for d in range(nb_days)}
            else:
                unavail_by_day = defaultdict(list)
                for (day, hd, hf) in raw_intervals:
                    unavail_by_day[day].append((hd, hf))
        html += f"<div id='room_{rn}' class='tab {active}'><h2>Salle {rn}{cap_str}</h2>"
        for w in range(nb_weeks):
            wp_active = "active" if w == 0 else ""
            html += f"<div class='week-pane {wp_active}' data-week='{w}'>"
            html += render_week(room_items[rn],
                                lambda item: f"{' + '.join(g.id for g in item.group)} · {item.teacher.name}",
                                unavail_by_day=unavail_by_day, week=w, _deadline_days=deadline_days)
            html += "</div>"
        html += "</div>"
    html += "</div>"

    def _fmt_day(abs_day):
        return fmt_abs_day(abs_day)

    if cancelled_items:
        html += "<div id='cancelled' class='tab'>"
        html += f"<h1 style='color:#c00'>⚠ Cours non placés ({len(cancelled_items)})</h1>"
        html += "<p style='margin:4px 20px;color:#666'>Ces cours n'ont pas pu être replanifiés lors de la résolution.</p>"
        html += "<table class='cancelled-table'>"
        html += "<tr><th>Cours</th><th>Type</th><th>Prof</th><th>Groupe(s)</th><th>Créneau original</th><th>Salle originale</th></tr>"
        for item in cancelled_items:
            cobj  = course_map_html.get(base_course_id(item.course))
            cname = cobj.name if cobj else str(item.course)
            grps  = ", ".join(g.id for g in item.group)
            stype = item.session_type or "—"
            html += (f"<tr><td><b>{cname}</b></td><td>{stype}</td>"
                     f"<td>{item.teacher.name}</td><td>{grps}</td>"
                     f"<td>{_fmt_day(item.day)} {item.heure_debut}–{item.heure_fin}</td>"
                     f"<td>{item.room}</td></tr>")
        html += "</table></div>"

    if deadline_violations:
        html += "<div id='deadlines' class='tab'>"
        html += f"<h1 style='color:#d06000'>⚠ Cours placés après leur deadline ({len(deadline_violations)})</h1>"
        html += "<p style='margin:4px 20px;color:#666'>Ces cours ont été replanifiés après leur date limite autorisée.</p>"
        html += "<table class='deadline-table'>"
        html += "<tr><th>Cours</th><th>Type</th><th>Prof</th><th>Groupe(s)</th><th>Nouveau créneau</th><th>Salle</th><th>Deadline (dernier jour autorisé)</th></tr>"
        for item in deadline_violations:
            cobj   = course_map_html.get(base_course_id(item.course))
            cname  = cobj.name if cobj else str(item.course)
            grps   = ", ".join(g.id for g in item.group)
            stype  = item.session_type or "—"
            dl_day = (deadline_days or {}).get(base_course_id(item.course))
            if dl_day is None:
                try: dl_day = (deadline_days or {}).get(int(base_course_id(item.course)))
                except (ValueError, TypeError): pass
            dl_str = _fmt_day(dl_day - DEADLINE_BUFFER_DAYS) if dl_day is not None else "—"
            html += (f"<tr><td><b>{cname}</b></td><td>{stype}</td>"
                     f"<td>{item.teacher.name}</td><td>{grps}</td>"
                     f"<td><b style='color:#c00'>{_fmt_day(item.day)}</b> {item.heure_debut}–{item.heure_fin}</td>"
                     f"<td>{item.room}</td>"
                     f"<td>{dl_str}</td></tr>")
        html += "</table></div>"

    if added_items:
        html += "<div id='added' class='tab'>"
        html += f"<h1 style='color:#1a7a3c'>✓ Sessions ajoutées ({len(added_items)})</h1>"
        html += "<p style='margin:4px 20px;color:#666'>Ces sessions ont été ajoutées avec succès à l'emploi du temps.</p>"
        html += "<table class='cancelled-table'>"
        html += "<tr><th>Cours</th><th>Type</th><th>Prof</th><th>Groupe(s)</th><th>Créneau</th><th>Salle</th></tr>"
        for item in added_items:
            cobj  = course_map_html.get(base_course_id(item.course))
            cname = cobj.name if cobj else str(item.course)
            grps  = ", ".join(g.id for g in item.group)
            stype = item.session_type or "—"
            html += (f"<tr><td><b>{cname}</b></td><td>{stype}</td>"
                     f"<td>{item.teacher.name}</td><td>{grps}</td>"
                     f"<td><b style='color:#1a7a3c'>{_fmt_day(item.day)}</b> {item.heure_debut}–{item.heure_fin}</td>"
                     f"<td>{item.room}</td></tr>")
        html += "</table></div>"

    if not_added_items:
        html += "<div id='not-added' class='tab'>"
        html += f"<h1 style='color:#6a3a8a'>⚠ Sessions non placées ({len(not_added_items)})</h1>"
        html += "<p style='margin:4px 20px;color:#666'>Ces sessions n'ont pas pu être ajoutées faute de créneau ou de salle disponible.</p>"
        html += "<table class='cancelled-table'>"
        html += "<tr><th>Cours</th><th>Type</th><th>Prof</th><th>Groupe(s)</th><th>Créneau demandé</th><th>Salle demandée</th></tr>"
        for item in not_added_items:
            cobj  = course_map_html.get(base_course_id(item.course))
            cname = cobj.name if cobj else str(item.course)
            grps  = ", ".join(g.id for g in item.group)
            stype = item.session_type or "—"
            req_day  = _fmt_day(item.day) if item.day is not None else "libre"
            req_slot = f"{req_day} {item.heure_debut or ''}".strip()
            req_room = item.room or "—"
            html += (f"<tr><td><b>{cname}</b></td><td>{stype}</td>"
                     f"<td>{item.teacher.name}</td><td>{grps}</td>"
                     f"<td style='color:#888'>{req_slot or '—'}</td>"
                     f"<td style='color:#888'>{req_room}</td></tr>")
        html += "</table></div>"

    if removed_items:
        html += "<div id='removed' class='tab'>"
        html += f"<h1 style='color:#1a7a3c'>✓ Sessions supprimées ({len(removed_items)})</h1>"
        html += "<p style='margin:4px 20px;color:#666'>Ces sessions ont été supprimées avec succès de l'emploi du temps.</p>"
        html += "<table class='cancelled-table'>"
        html += "<tr><th>Cours</th><th>Type</th><th>Prof</th><th>Groupe(s)</th><th>Créneau</th><th>Salle</th></tr>"
        for item in removed_items:
            cobj  = course_map_html.get(base_course_id(item.course))
            cname = cobj.name if cobj else str(item.course)
            grps  = ", ".join(g.id for g in item.group)
            stype = item.session_type or "—"
            html += (f"<tr><td><b>{cname}</b></td><td>{stype}</td>"
                     f"<td>{item.teacher.name}</td><td>{grps}</td>"
                     f"<td><b style='color:#1a7a3c'>{_fmt_day(item.day)}</b> {item.heure_debut}–{item.heure_fin}</td>"
                     f"<td>{item.room}</td></tr>")
        html += "</table></div>"

    if not_removed_items:
        html += "<div id='not-removed' class='tab'>"
        html += f"<h1 style='color:#c00'>⚠ Sessions non supprimées ({len(not_removed_items)})</h1>"
        html += "<p style='margin:4px 20px;color:#666'>Ces sessions n'ont pas pu être supprimées.</p>"
        html += "<table class='cancelled-table'>"
        html += "<tr><th>Cours</th><th>Type</th><th>Prof</th><th>Groupe(s)</th><th>Créneau</th><th>Salle</th></tr>"
        for item in not_removed_items:
            cobj  = course_map_html.get(base_course_id(item.course))
            cname = cobj.name if cobj else str(item.course)
            grps  = ", ".join(g.id for g in item.group)
            stype = item.session_type or "—"
            html += (f"<tr><td><b>{cname}</b></td><td>{stype}</td>"
                     f"<td>{item.teacher.name}</td><td>{grps}</td>"
                     f"<td style='color:#c00'>{_fmt_day(item.day)} {item.heure_debut}–{item.heure_fin}</td>"
                     f"<td>{item.room}</td></tr>")
        html += "</table></div>"

    html += "</body></html>"

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(html)
    print("Fichier généré :", filepath)


# ===========================================================================
# RAPPORT HTML HEURES ENSEIGNANTS
# ===========================================================================

def affichage_html_heures(
    schedule:        List[ScheduleItem],
    courses:         List,
    teachers:        List,
    filename:        str = "heures_profs.html",
    schedule_before: Optional[List[ScheduleItem]] = None,
    removed_items:   Optional[List[ScheduleItem]] = None,
    folder:          str = None,
):
    """
    Génère un rapport HTML des heures par enseignant.
    schedule_before : si fourni (ex: après remplacement), affiche les heures
                      avant/après et met en évidence les nouveaux cours assignés.
    """
    folder = folder or EDT_DIR
    os.makedirs(folder, exist_ok=True)
    filepath = os.path.join(folder, filename)

    course_map = {c.id: c for c in courses}
    course_map.update({str(c.id): c for c in courses})

    def _hours(sched, teacher_id):
        return sum(
            (hm(item.heure_fin) - hm(item.heure_debut)) / 60.0
            for item in sched
            if item.teacher.id == teacher_id
        )

    def _max_hours(teacher):
        if teacher.max_hours is not None:
            return teacher.max_hours
        if teacher.teacher_type:
            return MAX_HOURS_BY_TYPE.get(teacher.teacher_type)
        return None

    teacher_map = {t.id: t for t in teachers}
    for item in schedule:
        if item.teacher.id not in teacher_map:
            teacher_map[item.teacher.id] = item.teacher

    active_tids = sorted(set(item.teacher.id for item in schedule),
                         key=lambda tid: _hours(schedule, tid), reverse=True)

    # Détection des nouveaux cours assignés (remplacement)
    new_assignment_keys: set = set()
    if schedule_before is not None:
        before_keys = {
            (it.course, tuple(g.id for g in it.group), it.day, it.heure_debut, it.heure_fin): it.teacher.id
            for it in schedule_before
        }
        for item in schedule:
            k = (item.course, tuple(g.id for g in item.group), item.day, item.heure_debut, item.heure_fin)
            if before_keys.get(k) != item.teacher.id:
                new_assignment_keys.add(k)

    css = """
body { font-family: Arial, sans-serif; font-size: 13px; margin: 0; padding: 16px; background: #f7f8fa; }
h1 { font-size: 20px; margin-bottom: 16px; color: #222; }
.teacher-card { background: #fff; border: 1px solid #dde; border-radius: 6px;
                margin-bottom: 10px; overflow: hidden; }
.teacher-header { display: flex; align-items: center; padding: 10px 14px;
                  cursor: pointer; gap: 12px; user-select: none; }
.teacher-header:hover { background: #f0f2ff; }
.teacher-name { font-weight: bold; font-size: 14px; min-width: 140px; }
.teacher-type { font-size: 11px; padding: 2px 6px; border-radius: 10px;
                background: #e8eaff; color: #445; font-weight: bold; }
.hours-info { font-size: 12px; color: #555; min-width: 120px; }
.bar-wrap { flex: 1; background: #eee; border-radius: 4px; height: 12px;
            min-width: 80px; max-width: 200px; overflow: hidden; }
.bar-fill { height: 100%; border-radius: 4px; transition: width 0.3s; }
.bar-ok   { background: #4caf82; }
.bar-warn { background: #e6a020; }
.bar-over { background: #d44; }
.bar-none { background: #bbb; }
.quota-label { font-size: 11px; color: #666; min-width: 80px; }
.delta-badge { font-size: 11px; padding: 1px 6px; border-radius: 8px;
               font-weight: bold; margin-left: 4px; }
.delta-plus  { background: #ffe0b2; color: #b45000; }
.chevron { margin-left: auto; font-size: 12px; color: #888; transition: transform 0.2s; }
.chevron.open { transform: rotate(180deg); }
.teacher-detail { display: none; padding: 0 14px 12px; }
.teacher-detail.open { display: block; }
table { width: 100%; border-collapse: collapse; font-size: 12px; }
th { background: #f0f2ff; padding: 5px 8px; text-align: left;
     border-bottom: 1px solid #ccd; color: #445; }
td { padding: 4px 8px; border-bottom: 1px solid #eef; vertical-align: middle; }
tr:last-child td { border-bottom: none; }
tr:hover td { background: #fafbff; }
.new-badge { display: inline-block; font-size: 9px; font-weight: bold; padding: 1px 4px;
             border-radius: 3px; background: #2e9e5b; color: #fff;
             margin-left: 4px; vertical-align: middle; letter-spacing: 0.3px; }
.del-badge { display: inline-block; font-size: 9px; font-weight: bold; padding: 1px 4px;
             border-radius: 3px; background: #d44; color: #fff;
             margin-left: 4px; vertical-align: middle; letter-spacing: 0.3px; }
.stype-tag { display: inline-block; font-size: 9px; padding: 1px 4px; border-radius: 3px;
             background: rgba(0,0,0,0.12); color: #333; vertical-align: middle; }
.no-courses { color: #999; font-style: italic; padding: 8px 0; }
"""

    js = """
function toggle(id) {
    var det = document.getElementById('detail_' + id);
    var chv = document.getElementById('chev_' + id);
    det.classList.toggle('open');
    chv.classList.toggle('open');
}
"""

    def _bar_html(hours, max_h):
        if max_h is None:
            return "<div class='bar-wrap'><div class='bar-fill bar-none' style='width:100%'></div></div>"
        pct = min(100, round(hours / max_h * 100))
        cls = "bar-ok" if pct < 80 else ("bar-warn" if pct < 100 else "bar-over")
        return f"<div class='bar-wrap'><div class='bar-fill {cls}' style='width:{pct}%'></div></div>"

    def _row_html(item, is_new=False, is_removed=False):
        cobj  = course_map.get(base_course_id(item.course))
        cname = cobj.name if cobj else f"C{item.course}"
        jour  = fmt_abs_day(item.day)
        dur_h = (hm(item.heure_fin) - hm(item.heure_debut)) / 60.0
        stype = f"<span class='stype-tag'>{item.session_type}</span>" if item.session_type else ""
        if is_removed:
            badge     = "<span class='del-badge'>−SUP</span>"
            row_style = " style='opacity:0.55;text-decoration:line-through;background:#fff5f5'"
        elif is_new:
            badge     = "<span class='new-badge'>+NEW</span>"
            row_style = " style='background:#f0fff5'"
        else:
            badge     = ""
            row_style = ""
        return (f"<tr{row_style}>"
                f"<td>{cname}{badge}</td>"
                f"<td>{' + '.join(g.id for g in item.group)}</td>"
                f"<td>{stype}</td>"
                f"<td>{jour}</td>"
                f"<td>{item.heure_debut}–{item.heure_fin}</td>"
                f"<td>{item.room}</td>"
                f"<td style='text-align:right'>{dur_h:.2f}h</td>"
                f"</tr>")

    cards_html = ""
    for idx, tid in enumerate(active_tids):
        teacher  = teacher_map.get(tid)
        if teacher is None:
            continue
        tname   = teacher.name
        ttype   = teacher.teacher_type or "—"
        hours   = _hours(schedule, tid)
        max_h   = _max_hours(teacher)
        items   = sorted([it for it in schedule if it.teacher.id == tid],
                         key=lambda x: (x.day, hm(x.heure_debut)))

        quota_str  = f"{hours:.1f}h / {max_h:.0f}h" if max_h else f"{hours:.1f}h (pas de quota)"
        pct_str    = f"({round(hours/max_h*100)}%)" if max_h else ""

        delta_html = ""
        if schedule_before is not None:
            hours_before = _hours(schedule_before, tid)
            delta        = hours - hours_before
            if abs(delta) > 0.01:
                sign = "+" if delta > 0 else "−"
                delta_html = f"<span class='delta-badge delta-plus'>{sign}{abs(delta):.2f}h</span>"

        cards_html += f"""
<div class='teacher-card'>
  <div class='teacher-header' onclick='toggle({idx})'>
    <span class='teacher-name'>{tname}</span>
    <span class='teacher-type'>{ttype}</span>
    <span class='hours-info'>{quota_str} {pct_str}</span>
    {_bar_html(hours, max_h)}
    <span class='quota-label'>{delta_html}</span>
    <span class='chevron' id='chev_{idx}'>▼</span>
  </div>
  <div class='teacher-detail' id='detail_{idx}'>
"""
        removed_for_tid = sorted(
            [it for it in (removed_items or []) if it.teacher.id == tid],
            key=lambda x: (x.day, hm(x.heure_debut)),
        )
        if items or removed_for_tid:
            cards_html += """<table>
<tr><th>Cours</th><th>Groupe</th><th>Type séance</th>
    <th>Jour</th><th>Horaire</th><th>Salle</th><th>Durée</th></tr>
"""
            for item in items:
                k      = (item.course, tuple(g.id for g in item.group), item.day, item.heure_debut, item.heure_fin)
                is_new = k in new_assignment_keys
                cards_html += _row_html(item, is_new=is_new)
            for item in removed_for_tid:
                cards_html += _row_html(item, is_removed=True)
            cards_html += "</table>"
        else:
            cards_html += "<p class='no-courses'>Aucun cours ce créneau.</p>"

        cards_html += "  </div>\n</div>\n"

    title_suffix = " (après perturbations)" if (schedule_before is not None or removed_items) else ""
    html = f"""<html><head><meta charset='utf-8'>
<title>Heures enseignants{title_suffix}</title>
<style>{css}</style><script>{js}</script></head><body>
<h1>Heures enseignants{title_suffix}</h1>
{cards_html}
</body></html>"""

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Rapport heures généré : {filepath}")
