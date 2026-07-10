"""
BakuSim on OASIS - post-run analytics
======================================
Joins the OASIS simulation DB with agent demographics (sim_meta.json) and
prints the campaign report: reactions to the injected post by income quintile,
age band, district and language.

Usage:
    python analyze_results.py --db results/exp_001.db --post-author 1000

NOTE: OASIS table/column names may differ between versions (typical tables:
post, comment, like, dislike, follow, user). If a query fails, inspect the
schema first:  python analyze_results.py --db ... --schema
"""

import argparse
import json
import sqlite3
from collections import Counter
from pathlib import Path

BASE = Path(__file__).parent
DATA = BASE / "data"


def age_band(age: int) -> str:
    if age < 25:
        return "18-24"
    if age < 35:
        return "25-34"
    if age < 45:
        return "35-44"
    if age < 55:
        return "45-54"
    return "55+"


def breakdown(user_ids, demo, title):
    print(f"\n--- {title} (n={len(user_ids)}) ---")
    if not user_ids:
        return
    for dim, keyfn in [
        ("income quintile", lambda d: f"Q{d['income_quintile']}"),
        ("age band", lambda d: age_band(d["age"])),
        ("district", lambda d: d["district"]),
        ("language", lambda d: d["language"]),
    ]:
        counts = Counter(keyfn(demo[str(u)]) for u in user_ids if str(u) in demo)
        top = ", ".join(f"{k}: {v}" for k, v in counts.most_common(8))
        print(f"  {dim:16s} {top}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    parser.add_argument("--post-author", type=int, default=None,
                        help="agent id of the brand that posted (from sim_meta special_agents)")
    parser.add_argument("--schema", action="store_true", help="dump DB schema and exit")
    args = parser.parse_args()

    conn = sqlite3.connect(BASE / args.db)
    conn.row_factory = sqlite3.Row

    if args.schema:
        for row in conn.execute("SELECT name, sql FROM sqlite_master WHERE type='table'"):
            print(row["sql"], "\n")
        return

    meta = json.loads((DATA / "sim_meta.json").read_text(encoding="utf-8"))
    demo = meta["demographics"]

    # Injected posts = posts authored by the given brand/media agent
    if args.post_author is None:
        args.post_author = next(iter(meta["special_agents"].values()))
    posts = conn.execute(
        "SELECT post_id, content FROM post WHERE user_id = ?", (args.post_author,)
    ).fetchall()
    if not posts:
        raise SystemExit(f"No posts by agent {args.post_author} found in {args.db}")

    for post in posts:
        pid = post["post_id"]
        print("=" * 70)
        print(f"POST {pid}: {post['content'][:100]}")

        likes = [r["user_id"] for r in conn.execute(
            "SELECT user_id FROM 'like' WHERE post_id = ?", (pid,))]
        dislikes = [r["user_id"] for r in conn.execute(
            "SELECT user_id FROM dislike WHERE post_id = ?", (pid,))]
        comments = conn.execute(
            "SELECT user_id, content FROM comment WHERE post_id = ?", (pid,)).fetchall()
        reposts = [r["user_id"] for r in conn.execute(
            "SELECT user_id FROM post WHERE original_post_id = ?", (pid,))]

        print(f"\nTotals: {len(likes)} likes, {len(dislikes)} dislikes, "
              f"{len(comments)} comments, {len(reposts)} reposts")

        breakdown(likes, demo, "LIKES")
        breakdown(dislikes, demo, "DISLIKES")
        breakdown([c["user_id"] for c in comments], demo, "COMMENTS")
        breakdown(reposts, demo, "REPOSTS")

        if comments:
            print("\n--- sample comments ---")
            for c in comments[:10]:
                d = demo.get(str(c["user_id"]), {})
                tag = f"Q{d.get('income_quintile', '?')}/{d.get('age', '?')}y/{d.get('district', '?')}"
                print(f"  [{tag}] {c['content'][:120]}")


if __name__ == "__main__":
    main()
