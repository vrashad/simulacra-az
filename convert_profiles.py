"""
BakuSim -> OASIS profile converter
===================================
Reads data/baku_agents_1000.json (copy of profiles_v2), produces:

  data/baku_agents_oasis.csv  - Twitter-mode profile file for OASIS
                                (columns: name, username, user_char, description)
  data/sim_meta.json          - sidecar: activity levels, demographics for
                                analytics joins, follow edges (homophily graph),
                                ids of special brand/media agents

Agent ids in OASIS = CSV row order (0-based). Special agents (brands, media)
are appended AFTER the 1000 humans, so human ids stay 0..999.

Usage:
    python convert_profiles.py [--follows-mean 15] [--seed 42]
"""

import argparse
import csv
import json
import random
from pathlib import Path

BASE = Path(__file__).parent
DATA = BASE / "data"

# Special non-human agents appended after the 1000 humans.
SPECIAL_AGENTS = [
    {
        "key": "birmarket",
        "name": "Birmarket",
        "user_char": (
            "Sən Birmarket-in rəsmi sosial media hesabısan. Azərbaycanda onlayn "
            "marketplace. Aksiyalar, endirimlər və yeni məhsullar haqqında post yazırsan. "
            "Rəsmi, amma isti brend tonu."
        ),
        "description": "Birmarket - rəsmi hesab. Onlayn alış-veriş.",
        "follow_prob": 0.35,  # probability a human follows this account
    },
    {
        "key": "bravo",
        "name": "Bravo Supermarket",
        "user_char": (
            "Sən Bravo supermarketlər şəbəkəsinin rəsmi sosial media hesabısan. "
            "Endirimlər, kampaniyalar və mağaza yenilikləri haqqında post yazırsan."
        ),
        "description": "Bravo Supermarket - rəsmi hesab.",
        "follow_prob": 0.40,
    },
    {
        "key": "oxu_az",
        "name": "Oxu.az",
        "user_char": (
            "Sən Oxu.az xəbər portalının rəsmi hesabısan. Azərbaycan və dünya "
            "xəbərlərini neytral, informativ tonda paylaşırsan."
        ),
        "description": "Oxu.az - xəbər portalı.",
        "follow_prob": 0.55,
    },
]


def build_user_char(agent: dict) -> str:
    """Persona text the LLM sees: original persona + consumer traits + language rule."""
    cp = agent.get("consumer_profile", {})
    md = agent.get("metadata", {})

    consumer_lines = [
        f"Alıcı davranışın: qiymətə həssaslıq {cp.get('price_sensitivity', 0.5):.2f}, "
        f"impulsiv alış meyli {cp.get('impulse_buying', 0.5):.2f}, "
        f"endirimlərə reaksiya {cp.get('discount_responsiveness', 0.5):.2f}, "
        f"brendə sədaqət {cp.get('brand_loyalty', 0.5):.2f}.",
        f"Ənənəvi reklama inam: {cp.get('ad_trust_traditional', 0.5):.2f}, "
        f"influencer reklamına inam: {cp.get('ad_trust_influencer', 0.5):.2f}.",
        # preferred_brands intentionally NOT injected: the generator assigned
        # brands uniformly (~21% each), which dictated attitude toward any
        # advertised brand (72% vs 16% positive in ad_001) without real
        # market-share data behind it. Re-add only with calibrated weights.
        f"Onlayn alış-veriş tezliyi: {cp.get('online_shopping_frequency', 'nadir')}.",
        f"Gəlir qrupu: {md.get('income_label', '')} (~{md.get('monthly_income_azn', '?')} AZN/ay).",
    ]
    lang = agent.get("profile", {}).get("language", "az")
    lang_rule = (
        "Həmişə Azərbaycan dilində yaz." if lang == "az" else "Всегда пиши по-русски."
    )
    return (
        agent["persona"]
        + "\n\n"
        + "\n".join(consumer_lines)
        + "\n\n"
        + f"{lang_rule} Qısa, real insan kimi yaz — bəzən səhvlərlə, emosional. "
        + "Heç vaxt AI olduğunu demə."
    )


def homophily_score(a: dict, b: dict) -> float:
    """Similarity used as follow probability weight."""
    score = 0.0
    if a["metadata"]["district"] == b["metadata"]["district"]:
        score += 1.0
    age_a, age_b = a["profile"]["age"], b["profile"]["age"]
    score += max(0.0, 1.0 - abs(age_a - age_b) / 20.0)
    shared = set(a["profile"]["interests"]) & set(b["profile"]["interests"])
    score += 0.5 * len(shared)
    if a["profile"]["language"] == b["profile"]["language"]:
        score += 0.5
    return score


def generate_follow_edges(agents: list, follows_mean: int, rng: random.Random) -> list:
    """
    Homophily graph: each human follows ~follows_mean others, weighted by
    similarity, scaled by own activity_level. Plus hub effect: the 20 most
    active agents attract extra followers (influencers).
    Returns list of [follower_id, followee_id].
    """
    n = len(agents)
    hub_ids = sorted(range(n), key=lambda i: -agents[i].get("activity_level", 1.0))[:20]
    hub_set = set(hub_ids)
    edges = set()

    # Precompute candidate pool per agent from a random sample (full O(n^2) is
    # unnecessary; 120 candidates per agent gives a dense enough graph).
    for i, a in enumerate(agents):
        k = max(3, int(rng.gauss(follows_mean, follows_mean / 3)))
        k = int(k * min(2.0, max(0.3, a.get("activity_level", 1.0))))
        candidates = rng.sample(range(n), min(120, n))
        weights = []
        for j in candidates:
            if j == i:
                weights.append(0.0)
                continue
            w = homophily_score(a, agents[j])
            if j in hub_set:
                w += 2.0  # influencer boost
            weights.append(w)
        total = sum(weights)
        if total <= 0:
            continue
        chosen = set()
        for _ in range(k * 3):  # rejection sampling with cap
            if len(chosen) >= k:
                break
            r = rng.random() * total
            acc = 0.0
            for j, w in zip(candidates, weights):
                acc += w
                if acc >= r:
                    if j != i:
                        chosen.add(j)
                    break
        for j in chosen:
            edges.add((i, j))

    return sorted(edges)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--follows-mean", type=int, default=15)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    rng = random.Random(args.seed)
    agents = json.loads((DATA / "baku_agents_1000.json").read_text(encoding="utf-8"))
    print(f"Loaded {len(agents)} agents")

    # --- CSV rows: humans first (ids 0..999), then special agents ---
    rows = []
    for agent in agents:
        rows.append({
            "name": agent["name"],
            "username": agent["agent_id"],
            "user_char": build_user_char(agent),
            "description": (
                f"{agent['profile']['age']} yaş, {agent['metadata']['district']}, "
                f"{agent['profile']['occupation']}"
            ),
        })

    special_ids = {}
    for spec in SPECIAL_AGENTS:
        special_ids[spec["key"]] = len(rows)
        rows.append({
            "name": spec["name"],
            "username": spec["key"],
            "user_char": spec["user_char"],
            "description": spec["description"],
        })

    csv_path = DATA / "baku_agents_oasis.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["name", "username", "user_char", "description"])
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {csv_path} ({len(rows)} rows: {len(agents)} humans + {len(SPECIAL_AGENTS)} special)")

    # --- Follow edges ---
    edges = generate_follow_edges(agents, args.follows_mean, rng)
    # Humans follow special accounts with per-account probability
    for spec in SPECIAL_AGENTS:
        sid = special_ids[spec["key"]]
        for i in range(len(agents)):
            if rng.random() < spec["follow_prob"]:
                edges.append((i, sid))
    print(f"Generated {len(edges)} follow edges")

    # --- Sidecar meta for run/analytics ---
    meta = {
        "seed": args.seed,
        "num_humans": len(agents),
        "special_agents": special_ids,
        "follow_edges": edges,
        "activity_levels": {i: a.get("activity_level", 1.0) for i, a in enumerate(agents)},
        "demographics": {
            i: {
                "agent_id": a["agent_id"],
                "age": a["profile"]["age"],
                "gender": a["profile"]["gender"],
                "district": a["metadata"]["district"],
                "income_quintile": a["metadata"]["income_quintile"],
                "monthly_income_azn": a["metadata"]["monthly_income_azn"],
                "language": a["profile"]["language"],
            }
            for i, a in enumerate(agents)
        },
    }
    meta_path = DATA / "sim_meta.json"
    meta_path.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {meta_path}")


if __name__ == "__main__":
    main()
