#!/usr/bin/env python3
"""Extract the player's attack animation timing from the server's asset bundles -> <raw_dir>/anims/Player_animator.json.

Attack duration isn't an ItemDrop field: Attack.Start fires an animator trigger (m_attackAnimation, + chain level or
random index) and the attack lasts while the animator state is tagged "attack" (Player.InAttack). The state machine is
editor-only API at runtime, so the plugin can't dump it; UnityPy reads the serialized AnimatorController offline.

    scripts/extract-anims.py <server_dir> <raw_dump_dir>

Writes, per trigger that leads to an attack-tagged state:
  state, layer, speed (state speed multiplier), clip, length (clip seconds), exit (normalized exit time of the
  unconditional exit transition; none = loops until an abort trigger), offset (normalized start offset of the
  transition into it), events [[clip time, name, float?]]: Speed (CharacterAnimEvent.Speed sets animator.speed),
  Hit / OnAttackTrigger (Humanoid.OnAttackTrigger), Chain (CharacterAnimEvent.Chain: next chain level may start).
Fails if the controller or a clip is missing. Needs UnityPy (scripts/anims.sh sets up the venv).
"""
import json
import os
import sys
from pathlib import Path

import UnityPy

CONTROLLER = "Player_animator"
EVENTS = {"Speed", "Hit", "OnAttackTrigger", "Chain"}
SKIP_SUFFIXES = (".manifest", ".resS", ".resource", ".json", ".info", ".config", ".dll", ".so", ".txt", ".sh")
NO_CLIP = 0xFFFFFFFF
IF = 1  # AnimatorConditionMode.If: bool/trigger parameter set


def asset_files(data_dir: Path):
    for dirpath, dirnames, files in os.walk(data_dir):
        dirnames[:] = sorted(d for d in dirnames if d not in ("Managed", "MonoBleedingEdge", "Plugins"))
        for f in sorted(files):
            if not f.endswith(SKIP_SUFFIXES):
                yield Path(dirpath) / f


def find_controller(data_dir: Path):
    for path in asset_files(data_dir):
        try:
            env = UnityPy.load(str(path))
        except Exception:
            continue  # not a Unity asset file
        for obj in env.objects:
            if obj.type.name == "AnimatorController" and obj.peek_name() == CONTROLLER:
                return obj
    return None


def clip(obj, pptr: dict) -> dict:
    if pptr["m_FileID"] != 0 or pptr["m_PathID"] not in obj.assets_file.objects:
        raise SystemExit(f"ERROR: clip {pptr} of {CONTROLLER} is in another file")
    c = obj.assets_file.objects[pptr["m_PathID"]].read_typetree()
    mc = c["m_MuscleClip"]
    events = []
    for e in c["m_Events"]:
        if e["functionName"] in EVENTS:
            ev = [round(e["time"], 4), e["functionName"]]
            if e["functionName"] == "Speed":
                ev.append(round(e["floatParameter"], 4))
            events.append(ev)
    return {"clip": c["m_Name"], "length": round(mc["m_StopTime"] - mc["m_StartTime"], 4), "events": events}


def extract(obj) -> dict:
    tt = obj.read_typetree()
    tos = dict((h, n) for h, n in tt["m_TOS"])
    clips = tt["m_AnimationClips"]
    triggers: dict[str, dict] = {}
    for layer, sm in enumerate(tt["m_Controller"]["m_StateMachineArray"]):
        states = [s["data"] for s in sm["data"]["m_StateConstantArray"]]
        transitions = [t["data"] for t in sm["data"]["m_AnyStateTransitionConstantArray"]]
        transitions += [t["data"] for s in states for t in s["m_TransitionConstantArray"]]
        for t in transitions:
            dest = t["m_DestinationState"]
            if dest >= len(states) or tos.get(states[dest]["m_TagID"]) != "attack":
                continue
            s = states[dest]
            for c in t["m_ConditionConstantArray"]:
                c = c["data"]
                name = tos.get(c["m_EventID"])
                if c["m_ConditionMode"] != IF or not name:
                    continue
                ids = [n["data"]["m_ClipID"] for bt in s["m_BlendTreeConstantArray"] for n in bt["data"]["m_NodeArray"]]
                ids = [i for i in ids if i != NO_CLIP]
                if len(ids) != 1:
                    continue  # blend trees (upper-body loops) have no single timeline
                exits = [x["data"]["m_ExitTime"] for x in s["m_TransitionConstantArray"]
                         if x["data"]["m_HasExitTime"] and not x["data"]["m_ConditionConstantArray"]]
                state = tos.get(s["m_FullPathID"], str(s["m_NameID"]))
                if name in triggers and triggers[name]["state"] != state:
                    raise SystemExit(f"ERROR: trigger {name} leads to two attack states: {triggers[name]['state']}, {state}")
                triggers[name] = {
                    "state": state, "layer": layer,
                    "speed": round(s["m_Speed"], 4),
                    **clip(obj, clips[ids[0]]),
                    "exit": round(min(exits), 4) if exits else None,
                    "offset": round(t["m_TransitionOffset"], 4),
                }
    return {"controller": CONTROLLER, "triggers": dict(sorted(triggers.items()))}


def main() -> int:
    server, raw = Path(sys.argv[1]), Path(sys.argv[2])
    obj = find_controller(server / "valheim_server_Data")
    if obj is None:
        print(f"ERROR: AnimatorController {CONTROLLER} not found", file=sys.stderr)
        return 1
    out = raw / "anims" / f"{CONTROLLER}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    data = extract(obj)
    out.write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {len(data['triggers'])} attack triggers -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
