import argparse
import json
import time
import requests
from datetime import datetime
from pathlib import Path

def replay(input_path: str, api_url: str, speed: float):
    events = []
    with open(input_path) as f:
        for line in f:
            line = line.strip()
            if line:
                events.append(json.loads(line))

    if not events:
        print("No events found in file.")
        return

    total = len(events)
    print(f"Replaying {total} events at {speed}x speed → {api_url}")
    print("Press Ctrl+C to stop.\n")

    batch_size = 10
    delay      = 1.0 / speed   # seconds between batches

    sent = 0
    for i in range(0, total, batch_size):
        batch = events[i : i + batch_size]
        try:
            resp = requests.post(
                f"{api_url}/events/ingest",
                json={"events": batch},
                timeout=5
            )
            if resp.status_code == 200:
                data  = resp.json()
                sent += data["ingested"]
                pct   = int((i + len(batch)) / total * 100)
                print(f"\r[{pct:3d}%] Sent {sent}/{total} events", end="", flush=True)
            else:
                print(f"\nAPI error {resp.status_code}")
        except Exception as e:
            print(f"\nConnection error: {e}")
            time.sleep(1)

        time.sleep(delay)

    print(f"\n\nDone. {sent} events replayed.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input",  default="data/sample_events.jsonl")
    parser.add_argument("--api",    default="http://localhost:8000")
    parser.add_argument("--speed",  type=float, default=20.0,
                        help="Replay speed multiplier (20 = 20x faster than real-time)")
    args = parser.parse_args()
    replay(args.input, args.api, args.speed)