"""
BakuSim on OASIS - simulation runner
=====================================
Injects a post from a brand/media agent into the 1000-agent Baku population
and runs N steps of social dynamics.

Prereqs:
    pip install -r requirements.txt
    python convert_profiles.py          # once, creates CSV + sim_meta.json
    set OPENROUTER_API_KEY=sk-or-...

Usage:
    python run_simulation.py --post "Birmarket-də 50% endirim!" --poster birmarket ^
        --steps 30 --activation 0.15 --db results/exp_001.db

Model per docs/llm_selection_report.md: google/gemini-3.5-flash via OpenRouter,
no reasoning, temperature 1.0 for reaction diversity.

NOTE: verify API names against your installed oasis version
(https://docs.oasis.camel-ai.org) - the framework evolves quickly.
"""

import argparse
import asyncio
import json
import os
import random
from pathlib import Path

from camel.models import ModelFactory
from camel.types import ModelPlatformType

import oasis
from oasis import ActionType, LLMAction, ManualAction, generate_twitter_agent_graph

BASE = Path(__file__).parent
DATA = BASE / "data"

AVAILABLE_ACTIONS = [
    ActionType.LIKE_POST,
    ActionType.DISLIKE_POST,
    ActionType.CREATE_COMMENT,
    ActionType.REPOST,
    ActionType.CREATE_POST,
    ActionType.FOLLOW,
    ActionType.DO_NOTHING,
]


def make_model(model_type="google/gemini-3.5-flash"):
    # NOTE: do not set max_tokens here - CAMEL treats it as the TOTAL
    # context budget and truncates the agent's persona/feed to fit it
    # (verified in smoke_001/news_001: limit=512 truncation -> 100% do_nothing)
    config = {"temperature": 1.0}
    if "gemini-3.5-flash" in model_type:
        # reasoning cannot be fully disabled for gemini-3.5-flash on
        # OpenRouter (400: "Reasoning is mandatory for this endpoint"),
        # so pin it to the cheapest tier. Other models (e.g. 3.1-flash-lite)
        # default to no reasoning - send the request clean.
        config["extra_body"] = {"reasoning": {"effort": "low"}}
    return ModelFactory.create(
        model_platform=ModelPlatformType.OPENAI_COMPATIBLE_MODEL,
        model_type=model_type,
        url="https://openrouter.ai/api/v1",
        api_key=os.environ["OPENROUTER_API_KEY"],
        model_config_dict=config,
    )


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--post", required=True, help="text of the injected post")
    parser.add_argument("--poster", default="birmarket",
                        help="who posts: birmarket | bravo | oxu_az")
    parser.add_argument("--steps", type=int, default=30)
    parser.add_argument("--activation", type=float, default=0.15,
                        help="base share of humans activated per step")
    parser.add_argument("--max-active", type=int, default=60,
                        help="hard cap on activated agents per step (cost control)")
    parser.add_argument("--max-calls", type=int, default=1500,
                        help="hard budget: stop the run after this many LLM activations")
    parser.add_argument("--keep-memory", action="store_true",
                        help="keep agent chat history between steps (EXPENSIVE: "
                             "context grows 6k->12k->17k+ tokens per reactivation; "
                             "default is to reset memory after each step)")
    parser.add_argument("--model", default="google/gemini-3.5-flash",
                        help="OpenRouter model id for agent reactions "
                             "(check cost first: python probe_cost.py --model <id>)")
    parser.add_argument("--db", default="results/simulation.db")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    rng = random.Random(args.seed)
    meta = json.loads((DATA / "sim_meta.json").read_text(encoding="utf-8"))
    activity = {int(k): v for k, v in meta["activity_levels"].items()}
    poster_id = meta["special_agents"][args.poster]

    db_path = BASE / args.db
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        raise SystemExit(f"{db_path} already exists - use a new --db per experiment")

    model = make_model(args.model)
    agent_graph = await generate_twitter_agent_graph(
        profile_path=str(DATA / "baku_agents_oasis.csv"),
        model=model,
        available_actions=AVAILABLE_ACTIONS,
    )

    env = oasis.make(
        agent_graph=agent_graph,
        platform=oasis.DefaultPlatformType.TWITTER,
        database_path=str(db_path),
    )
    await env.reset()

    # --- Step 0a: build the social graph (manual actions are DB ops, no LLM cost) ---
    print(f"Applying {len(meta['follow_edges'])} follow edges...")
    follow_actions = {}
    for follower_id, followee_id in meta["follow_edges"]:
        agent = env.agent_graph.get_agent(follower_id)
        follow_actions.setdefault(agent, []).append(
            ManualAction(action_type=ActionType.FOLLOW,
                         action_args={"followee_id": followee_id})
        )
    await env.step(follow_actions)

    # --- Step 0b: inject the post ---
    print(f"Injecting post from '{args.poster}' (agent {poster_id}): {args.post[:60]}...")
    poster = env.agent_graph.get_agent(poster_id)
    await env.step({poster: ManualAction(
        action_type=ActionType.CREATE_POST, action_args={"content": args.post}
    )})

    # --- Steps 1..N: agents live their lives ---
    num_humans = meta["num_humans"]
    total_calls = 0
    for step in range(1, args.steps + 1):
        active = [
            env.agent_graph.get_agent(i)
            for i in range(num_humans)
            if rng.random() < args.activation * min(2.0, max(0.2, activity.get(i, 1.0)))
        ]
        if len(active) > args.max_active:
            active = rng.sample(active, args.max_active)
        if total_calls + len(active) > args.max_calls:
            print(f"Step {step}: LLM call budget reached "
                  f"({total_calls}/{args.max_calls}), stopping early")
            break
        total_calls += len(active)
        print(f"Step {step}/{args.steps}: activating {len(active)} agents "
              f"(calls so far: {total_calls}/{args.max_calls})")
        await env.step({agent: LLMAction() for agent in active})

        # Reset per-agent chat history (persona survives - it is the system
        # message that reset() re-adds). Without this, every reactivated
        # agent resends its whole accumulated history: input tokens grow
        # 6k -> 12k -> 17k+ per agent and dominate the bill.
        if not args.keep_memory:
            for agent in active:
                agent.reset()

    await env.close()
    print(f"\nDone. Results in {db_path}")
    print(f"Analyze:  python analyze_results.py --db {args.db} --post-author {poster_id}")


if __name__ == "__main__":
    asyncio.run(main())
