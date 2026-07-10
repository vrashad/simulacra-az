"""
Smoke series: injects 3 reference posts (brand promo / positive news /
negative news) and runs a short simulation for each.
Post texts live in this file - nothing to paste into the console.

Usage (any shell):
    python run_smoke.py [--demo] [--model <openrouter-model-id>]
If OPENROUTER_API_KEY is not set, the script asks for it interactively.
"""

import argparse
import getpass
import os
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).parent

RUNS = [
    ("birmarket", "ad",
     "Yayın cırhacırında istilər bizə gəlməmiş, hazırlıqlı ol. Belə ki, "
     "IFFALCON kondisionerlərini 15 iyuladək düz 45%-dək endirimlə Birmarket.az "
     "dan əldə edə bilərsən. Sən də sərinliyi evinə gətir, yayı daha rahat keçir. "
     "Üstəlik quraşdırma xidməti də mövcuddur. Tələs, bu fürsəti qaçırma"),
    ("oxu_az", "pension",
     "Azərbaycanda minimum pensiya və əməkhaqları 50 faiz artırılacaq. "
     "Qərar növbəti aydan qüvvəyə minəcək."),
    ("oxu_az", "negative",
     "Azərbaycanda elektrik enerjisi və qazın tarifləri noyabrın 1-dən 40 faiz "
     "bahalaşacaq. Kommunal xidmətlərin qiymət artımı bütün əhaliyə şamil olunacaq."),
]

SIM_ARGS = ["--steps", "5", "--activation", "0.05",
            "--max-active", "50", "--max-calls", "300"]

# demo mode: ~25 activations per post - just enough reactions to show
DEMO_ARGS = ["--steps", "2", "--activation", "0.03",
             "--max-active", "15", "--max-calls", "25"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="google/gemini-3.1-flash-lite",
                        help="OpenRouter model id for agent reactions")
    parser.add_argument("--demo", action="store_true",
                        help="tiny demo run: ~25 activations per post")
    args = parser.parse_args()

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    if not env.get("OPENROUTER_API_KEY"):
        env["OPENROUTER_API_KEY"] = getpass.getpass("OPENROUTER_API_KEY: ").strip()

    tag = args.model.split("/")[-1]
    sim_args = DEMO_ARGS if args.demo else SIM_ARGS
    prefix = "demo" if args.demo else "smoke"
    dbs = []
    for poster, name, post in RUNS:
        db = f"results/{prefix}_{name}_{tag}.db"
        dbs.append((db, poster))
        if (BASE / db).exists():
            print(f"\n=== {db} already exists, skipping (delete it to rerun)")
            continue
        print(f"\n=== RUN: {db} (poster={poster}, model={args.model})")
        r = subprocess.run(
            [sys.executable, str(BASE / "run_simulation.py"),
             "--post", post, "--poster", poster, "--db", db,
             "--model", args.model, *sim_args],
            env=env, cwd=BASE,
        )
        if r.returncode != 0:
            print(f"!!! {db} failed (exit {r.returncode}), stopping the series")
            sys.exit(r.returncode)

    print("\nAll done. Analyze:")
    for db, poster in dbs:
        author = 1000 if poster == "birmarket" else 1002
        print(f"  python analyze_results.py --db {db} --post-author {author}")


if __name__ == "__main__":
    main()
