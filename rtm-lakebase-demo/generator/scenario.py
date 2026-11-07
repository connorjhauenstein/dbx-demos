import json, argparse, pathlib

STATE_FILE = pathlib.Path("/tmp/rtm_scenario.json")

def load():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"dropped_venues": [], "widened": {}}

def save(state):
    STATE_FILE.write_text(json.dumps(state))

p = argparse.ArgumentParser()
sub = p.add_subparsers(dest="cmd")

drop_p = sub.add_parser("drop")
drop_p.add_argument("--venue", required=True)

widen_p = sub.add_parser("widen")
widen_p.add_argument("--symbol", required=True)
widen_p.add_argument("--bps", type=float, required=True)

reset_p = sub.add_parser("reset")

args = p.parse_args()
state = load()

if args.cmd == "drop":
    if args.venue not in state["dropped_venues"]:
        state["dropped_venues"].append(args.venue)
    print(f"Dropped: {state['dropped_venues']}")
elif args.cmd == "widen":
    state["widened"][args.symbol] = args.bps
    print(f"Widened: {state['widened']}")
elif args.cmd == "reset":
    state = {"dropped_venues": [], "widened": {}}
    print("Reset")

save(state)
