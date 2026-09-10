import json, os, sys, time, random, pathlib
from datetime import datetime, timezone
from confluent_kafka import Producer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # repo root
import config as cfg

BOOTSTRAP = cfg.KAFKA_BOOTSTRAP
TOPIC     = cfg.KAFKA_TOPIC
RATE      = cfg.GEN_RATE_PER_SYMBOL

SYMBOLS = ["BTC-USD", "ETH-USD", "DOGE-USD"]
VENUES  = ["gemini", "mm_a", "mm_b", "mm_c"]

MID    = {"BTC-USD": 78000.0, "ETH-USD": 2467.0, "DOGE-USD": 0.086}
BASE_SPREAD_BPS = {"gemini": 3.0, "mm_a": 2.5, "mm_b": 2.0, "mm_c": 5.0}
MID_VOL = {"BTC-USD": 0.0005, "ETH-USD": 0.0006, "DOGE-USD": 0.002}

STATE_FILE = pathlib.Path("/tmp/rtm_scenario.json")

producer = Producer({
    "bootstrap.servers": BOOTSTRAP,
    "queue.buffering.max.messages": 1000000,
    "queue.buffering.max.kbytes": 524288,
})

seq = {s: 0 for s in SYMBOLS}
mid = dict(MID)
spread = {v: float(BASE_SPREAD_BPS[v]) for v in VENUES}
interval = 1.0 / (RATE * len(SYMBOLS))

def scenario():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"dropped_venues": [], "widened": {}}

while True:
    s = scenario()
    for venue in VENUES:
        spread[venue] = max(0.5, spread[venue] * 0.95 + BASE_SPREAD_BPS[venue] * 0.05 + random.gauss(0, 0.05))
    for symbol in SYMBOLS:
        mid[symbol] *= 1 + random.gauss(0, MID_VOL[symbol])
        for venue in VENUES:
            if venue in s["dropped_venues"]:
                continue
            extra_bps = s["widened"].get(symbol, 0) if venue == "gemini" else 0
            half = mid[symbol] * (spread[venue] + extra_bps) / 20000
            bid, ask = mid[symbol] - half, mid[symbol] + half
            seq[symbol] += 1
            msg = {
                "event_ts": datetime.now(timezone.utc).isoformat(),
                "symbol": symbol, "venue": venue,
                "bid": round(bid, 8), "ask": round(ask, 8),
                "bid_sz": round(random.uniform(0.5, 2.0), 4),
                "ask_sz": round(random.uniform(0.5, 2.0), 4),
                "depth_bid_5": round(random.uniform(1.5, 5.0), 2),
                "depth_ask_5": round(random.uniform(1.5, 5.0), 2),
                "seq": seq[symbol],
            }
            producer.produce(
                TOPIC,
                key=f"{symbol}|{venue}",
                value=json.dumps(msg).encode()
            )
        producer.poll(0)
    time.sleep(interval)
