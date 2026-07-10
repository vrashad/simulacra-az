"""
BakuSim - universal comment classification
============================================
One LLM pass labels EVERY dimension of each comment at once (works for ads,
news, any post type - non-applicable fields come back as "na"):

  sentiment:  positive | neutral | negative
  stance:     support | oppose | worried | skeptical | question | sarcasm | indifferent
              (münasibət postun mövzusuna)
  intent:     buy_intent | considering | no_intent | na
              (commercial posts only, otherwise "na")
  objection:  price | trust | quality | availability | other | none
  competitor_name: mentioned competitor brand or null

Labels are cached in table `comment_labels` inside the run DB (schema v2);
rerunning only labels new comments.

Usage:
    set OPENROUTER_API_KEY=sk-or-...
    python classify_comments.py --db results/ad_001.db --post-author 1000

Cost: ~220 comments / 20 per call = ~11 calls of gemini-flash (< $0.05).
"""

import argparse
import json
import os
import sqlite3
from collections import Counter
from pathlib import Path

import requests

BASE = Path(__file__).parent
DATA = BASE / "data"

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL = "google/gemini-3.5-flash"
BATCH = 20

LABEL_COLS = ("sentiment", "stance", "intent", "objection", "competitor_name")

PROMPT = """Sən sosial media analitiksən. Aşağıda bir posta yazılmış şərhlər var.

POST: {post}

Hər şərh üçün BÜTÜN sahələri doldur və JSON qaytar:
- "id": şərhin nömrəsi
- "sentiment": "positive" | "neutral" | "negative" - şərhin ümumi emosional tonu
- "stance": postun MÖVZUSUNA münasibət:
    "support"     - dəstəkləyir / sevinir
    "oppose"      - əleyhinədir / qəzəblidir
    "worried"     - narahatdır (qiymətlər, gələcək və s.)
    "skeptical"   - inanmır / şübhə ilə yanaşır
    "question"    - əsasən sual verir
    "sarcasm"     - istehza / sarkazm
    "indifferent" - laqeyd
- "intent": kommersiya təklifinə münasibətdə niyyət:
    "buy_intent"  - almaq/istifadə etmək niyyəti açıq bildirilir
    "considering" - maraqlanır, düşünür, müqayisə edir
    "no_intent"   - almayacağını bildirir və ya rədd edir
    "na"          - post kommersiya təklifi deyil və ya niyyət mövzusu yoxdur
- "objection": əsas etiraz növü:
    "price"        - qiymət / imkan çatmır (kommunal xərclər, maaş az və s.)
    "trust"        - brendə/mənbəyə/hakimiyyətə inamsızlıq
    "quality"      - keyfiyyət şübhəsi
    "availability" - çatdırılma / quraşdırma / əlçatanlıq problemi
    "other"        - başqa etiraz
    "none"         - etiraz yoxdur
- "competitor_name": rəqib brend adı çəkilibsə adı (məs. "Kontakt Home"), yoxdursa null

YALNIZ JSON array qaytar, başqa heç nə:
[{{"id":0,"sentiment":"...","stance":"...","intent":"...","objection":"...","competitor_name":null}}, ...]

ŞƏRHLƏR:
{comments}"""


def classify_batch(post_text, batch, api_key):
    comments_txt = "\n".join(f"{i}. {c}" for i, c in batch)
    resp = requests.post(
        OPENROUTER_URL,
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": MODEL,
            "temperature": 0.0,
            "messages": [{
                "role": "user",
                "content": PROMPT.format(post=post_text[:500], comments=comments_txt),
            }],
        },
        timeout=120,
    )
    resp.raise_for_status()
    text = resp.json()["choices"][0]["message"]["content"].strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        text = text[4:] if text.startswith("json") else text
    return json.loads(text)


def ensure_schema(conn):
    """Schema v2 (5 label columns). Drop stale v1 cache if present."""
    cols = [r[1] for r in conn.execute("PRAGMA table_info(comment_labels)")]
    if cols and "stance" not in cols:
        conn.execute("DROP TABLE comment_labels")
        print("(old v1 label cache dropped - will relabel with full schema)")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS comment_labels ("
        "comment_id INTEGER PRIMARY KEY, sentiment TEXT, stance TEXT, "
        "intent TEXT, objection TEXT, competitor_name TEXT)"
    )


def crosstab(labeled, demo, field, cats):
    print(f"\n{field.upper()} x INCOME QUINTILE:")
    print("  " + " ".join(f"{c[:10]:>11s}" for c in cats))
    for q in (1, 2, 3, 4, 5):
        row = Counter(
            r[field] for r in labeled
            if str(r["user_id"]) in demo and demo[str(r["user_id"])]["income_quintile"] == q
        )
        print(f"  Q{q}: " + " ".join(f"{row.get(c, 0):>10d}" for c in cats))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    parser.add_argument("--post-author", type=int, required=True)
    args = parser.parse_args()

    api_key = os.environ.get("OPENROUTER_API_KEY")
    conn = sqlite3.connect(BASE / args.db)
    conn.row_factory = sqlite3.Row
    ensure_schema(conn)

    demo = json.loads((DATA / "sim_meta.json").read_text(encoding="utf-8"))["demographics"]

    for post in conn.execute(
        "SELECT post_id, content FROM post WHERE user_id = ?", (args.post_author,)
    ).fetchall():
        rows = conn.execute(
            "SELECT c.comment_id, c.user_id, c.content FROM comment c "
            "LEFT JOIN comment_labels l ON l.comment_id = c.comment_id "
            "WHERE c.post_id = ? AND l.comment_id IS NULL", (post["post_id"],)
        ).fetchall()
        print(f"POST {post['post_id']}: {len(rows)} unlabeled comments")

        if rows and not api_key:
            raise SystemExit("OPENROUTER_API_KEY is not set")

        for start in range(0, len(rows), BATCH):
            chunk = rows[start:start + BATCH]
            batch = [(i, r["content"]) for i, r in enumerate(chunk)]
            try:
                labels = classify_batch(post["content"], batch, api_key)
            except (json.JSONDecodeError, requests.RequestException) as e:
                print(f"  batch {start//BATCH}: FAILED ({e}), skipping")
                continue
            by_id = {item["id"]: item for item in labels}
            for i, r in enumerate(chunk):
                lab = by_id.get(i)
                if lab:
                    conn.execute(
                        "INSERT OR REPLACE INTO comment_labels VALUES (?,?,?,?,?,?)",
                        (r["comment_id"], *(lab.get(c) for c in LABEL_COLS)),
                    )
            conn.commit()
            print(f"  labeled {min(start+BATCH, len(rows))}/{len(rows)}")

        # --- report ---
        labeled = conn.execute(
            "SELECT c.user_id, l.* FROM comment c "
            "JOIN comment_labels l ON l.comment_id = c.comment_id "
            "WHERE c.post_id = ?", (post["post_id"],)
        ).fetchall()
        if not labeled:
            continue

        print(f"\n===== POST {post['post_id']}: {post['content'][:80]}")
        print(f"labeled comments: {len(labeled)}")

        for field in ("sentiment", "stance", "intent", "objection"):
            counts = Counter(r[field] for r in labeled)
            print(f"\n{field.upper()}:")
            for k, v in counts.most_common():
                print(f"  {str(k):16s} {v:4d}  ({100*v/len(labeled):.0f}%)")

        competitors = Counter(r["competitor_name"] for r in labeled if r["competitor_name"])
        if competitors:
            print("\nCOMPETITORS MENTIONED:")
            for k, v in competitors.most_common(10):
                print(f"  {k:20s} {v}")

        crosstab(labeled, demo, "stance",
                 ["support", "oppose", "worried", "skeptical", "question", "sarcasm"])
        intents = {r["intent"] for r in labeled}
        if intents - {"na", None}:
            crosstab(labeled, demo, "intent",
                     ["buy_intent", "considering", "no_intent", "na"])
            crosstab(labeled, demo, "objection",
                     ["price", "trust", "quality", "availability", "other", "none"])


if __name__ == "__main__":
    main()
