"""
Probe the real per-call cost of the simulation config on OpenRouter.
Sends ONE sim-sized request per config variant and prints exact billed cost
(via GET /api/v1/generation). Total probe cost: a few cents.

Usage:
    python probe_cost.py
"""

import argparse
import getpass
import json
import os
import time

import requests

URL = "https://openrouter.ai/api/v1/chat/completions"

# realistic simulation-sized prompt (persona + feed + action instruction)
SYSTEM = ("Sən Murad Axundov, 28 yaşında, Xəzər rayonunda yaşayırsan. Ticarət sahəsində "
          "çalışırsan. Xarakter: sadə, sakit, pessimist. Aylıq gəlir: ~1758 AZN. "
          "Alıcı davranışın: qiymətə həssaslıq 0.22, endirimlərə reaksiya 0.28. "
          "Həmişə Azərbaycan dilində yaz. Sən Twitter istifadəçisisən.") * 3

USER = ("After refreshing, you see some posts: [post_id 1, from Birmarket: 'IFFALCON "
        "kondisionerlərinə 45% endirim, quraşdırma daxil']. Pick one action that best "
        "reflects your inclination: like_post, dislike_post, create_comment, repost, "
        "do_nothing. Answer with the action and, if commenting, the comment text.") * 2

VARIANTS = [
    ("plain (no reasoning param)", {}),
    ("effort=low", {"reasoning": {"effort": "low"}}),
]


def probe(api_key, name, extra, model):
    body = {
        "model": model,
        "temperature": 1.0,
        "usage": {"include": True},  # ask OpenRouter to return billed cost inline
        "messages": [{"role": "system", "content": SYSTEM},
                     {"role": "user", "content": USER}],
        **extra,
    }
    r = requests.post(URL, headers={"Authorization": f"Bearer {api_key}"},
                      json=body, timeout=120)
    if r.status_code != 200:
        print(f"\n[{name}] HTTP {r.status_code}: {r.text[:300]}")
        return
    data = r.json()
    usage = data.get("usage", {})
    cost = usage.get("cost")
    provider = data.get("provider", "?")
    if cost is None:  # fallback: generation endpoint (needs a short delay)
        gen_id = data.get("id")
        for _ in range(5):
            time.sleep(3)
            g = requests.get(f"https://openrouter.ai/api/v1/generation?id={gen_id}",
                             headers={"Authorization": f"Bearer {api_key}"}, timeout=60)
            info = g.json().get("data") or {}
            if info.get("total_cost") is not None:
                cost = info["total_cost"]
                provider = info.get("provider_name", provider)
                break
    det = usage.get("completion_tokens_details") or {}
    print(f"\n[{name}]")
    print(f"  provider:          {provider}")
    print(f"  prompt tokens:     {usage.get('prompt_tokens', '?')}")
    print(f"  completion tokens: {usage.get('completion_tokens', '?')}")
    print(f"  reasoning tokens:  {det.get('reasoning_tokens', '?')}")
    print(f"  BILLED COST:       ${cost}")
    if cost is not None:
        print(f"  -> 300 activations x ~2.5 requests each: ${300*2.5*float(cost):.2f}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="google/gemini-3.5-flash",
                        help="OpenRouter model id to probe")
    args = parser.parse_args()
    api_key = os.environ.get("OPENROUTER_API_KEY") or getpass.getpass("OPENROUTER_API_KEY: ").strip()
    print(f"Probing model: {args.model}")
    for name, extra in VARIANTS:
        try:
            probe(api_key, name, extra, args.model)
        except Exception as e:
            print(f"\n[{name}] failed: {e}")


if __name__ == "__main__":
    main()
