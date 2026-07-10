# Simulacra-AZ

**Synthetic social-media audience of Baku, Azerbaijan — 1,000 LLM agents built from official
statistics, running on [OASIS](https://github.com/camel-ai/oasis)/CAMEL, for pre-testing
marketing campaigns and news content before real-world launch.**

Inject a post (a promo, a news item) into a simulated social network and observe how a
demographically realistic population reacts: who likes it, who comments and what they say,
what objections they raise, and how the reaction splits by income, age, district and language.

---

## 1. What this is

| | |
|---|---|
| Population | 1,000 agents: age, gender, district, occupation, income quintile (Q1–Q5), language (az/ru/mixed), consumer traits — sampled from official Azerbaijani statistics (see §4) |
| Platform | OASIS multi-agent social simulator (Twitter mode): feed, recommender system, follow graph, 7 agent actions |
| Agent engine | `google/gemini-3.5-flash` via OpenRouter (benchmark-selected, see §5); any OpenRouter model can be swapped in with `--model` |
| Analytics | Demographic breakdowns of every reaction + an LLM-judge that labels each comment with sentiment / stance / purchase intent / objection type / competitor mentions |
| Cost | Demo run: ~$1.3 · Standard test: ~$16 · Cheap-model demo: ~$0.05 (see §6) |

**Positioning: a compass, not a ruler.** Directional conclusions (campaign A vs campaign B,
which segment reacts stronger, what the dominant objection is) are supported by the
validation runs below. Absolute percentages (exact engagement rates) are not calibrated
against real campaign data yet — that is the roadmap item №1 (§10).

---

## 2. Pipeline

```
official statistics (data/azerbaijan_stats/)
        │  generate_profiles (upstream, simulacra-core)
        ▼
baku_agents_1000.json  ──►  convert_profiles.py  ──►  baku_agents_oasis.csv + sim_meta.json
                                                        (personas, homophily follow graph
                                                         ~17k edges, 3 brand/media accounts)
        ▼
run_simulation.py / run_smoke.py
   step 0: apply follow graph, inject the post (ManualAction, no LLM cost)
   steps 1..N: activity-weighted subsample of agents observes the feed and acts
               (like / dislike / comment / repost / follow / post / nothing)
        ▼
results/<experiment>.db   (SQLite: posts, comments, likes, follows, full action trace)
        ▼
analyze_results.py        reactions × income / age / district / language
classify_comments.py      LLM-judge labels per comment: sentiment, stance,
                          intent, objection, competitor  (cached in the same DB)
```

Agent IDs 0–999 are humans; 1000 = **Birmarket** (brand), 1001 = **Bravo** (brand),
1002 = **Oxu.az** (news media). Humans follow the brand/media accounts with realistic
probabilities (35–55%) and each other via homophily (district / age / interests / language),
including 20 high-activity "influencer" hubs.

---

## 3. Repository layout

```
simulacra-az/
├── README.md                  ← this document
├── requirements.txt
├── convert_profiles.py        # profiles JSON → OASIS CSV + social graph (deterministic, seed 42)
├── run_simulation.py          # single experiment: inject post, run N steps, hard cost caps
├── run_smoke.py               # standard 3-post series (promo / positive news / negative news)
├── analyze_results.py         # demographic reaction report from a run DB
├── classify_comments.py       # universal LLM-judge comment classification
├── probe_cost.py              # measure real per-request cost of any model before running
├── data/
│   ├── baku_agents_1000.json  # 1,000 agent profiles (source of truth)
│   ├── baku_agents_oasis.csv  # generated: personas in OASIS format
│   ├── sim_meta.json          # generated: follow graph, activity levels, demographics index
│   ├── demographic_summary.json
│   ├── system_prompt.txt
│   ├── azerbaijan_stats/      # official statistics the profiles are built from (provenance)
│   └── validation/            # scraped oxu.az news corpus (for future calibration)
├── docs/
│   └── llm_selection_report.md  # full model-selection benchmark report (Russian)
└── results/
    ├── demo_ad_gemini-3.5-flash.db        # included sample runs (demo scale)
    ├── demo_pension_gemini-3.5-flash.db
    └── demo_negative_gemini-3.5-flash.db
```

---

## 4. Data provenance

Agent profiles are **not** free-form LLM inventions. They are sampled from official
Azerbaijani statistics stored in `data/azerbaijan_stats/` (State Statistical Committee
publications): population by age/sex/territory, household composition, employment and
wages by territory, digital development, household survey results. Derived per-agent
attributes: district of Baku, age, gender, occupation, education, marital status, income
quintile with monthly income in AZN (Q1 ≈ 220 AZN/person … Q5 ≈ 628 AZN/person),
internet access (age-dependent), language of social-media use, activity level, and
scalar consumer traits (price sensitivity, discount responsiveness, impulse buying,
brand loyalty, ad trust).

Each agent's persona (what the LLM sees) = biography in Azerbaijani + consumer traits +
income group + a language rule (az/ru). Example persona features surface directly in
reactions: a 66-year-old pensioner worries about paying utility bills from her pension,
a Q1 student complains about rent on a 700-AZN salary.

---

## 5. Model selection (benchmarks)

Full methodology and statistics: [`docs/llm_selection_report.md`](docs/llm_selection_report.md).
Two public benchmarks were run via OpenRouter (seed 42, temperature 0, identical question
samples across models):

- **TwinVoice/TwinBench D1** — persona fidelity: identify the authentic reply of a specific
  persona (1-of-4, chance = 25%).
- **SimBench (Grouped)** — group simulation fidelity: predict a demographic group's answer
  distribution; scored by Total Variation distance, normalized against a uniform baseline.

| Model | TwinBench D1 (n=250) | SimBench score | Verdict |
|---|---|---|---|
| openai/gpt-5.5 | 54.4% | **55.6** | frontier tie |
| **google/gemini-3.5-flash** | **57.6%** | 54.2 (n=1500) | frontier tie → **selected** (cheapest ops) |
| anthropic/claude-sonnet-5 | 46–50% (n=50) | 51.0 | frontier tie (lower edge) |
| x-ai/grok-4.3 | — | 47.6 | frontier tie (lower edge), 2× slower |
| google/gemini-3.1-flash-lite | 44.8% | 44.9 | **measurably worse** (−12.8 pp on D1, >4σ) |

Key findings that shaped the setup:

1. **Frontier models are a statistical plateau** on both benchmarks → the choice was made
   on economics (speed 2.6 s/call, 0 format failures in ~1600 calls).
2. **Reasoning does not improve persona simulation** (verified on 3 models) → simulation
   runs with reasoning pinned to the minimum the endpoint allows.
3. **Cheap-tier models are NOT on the plateau**: gemini-3.1-flash-lite drops persona
   fidelity significantly. Policy: lite-class models for pipeline development and demos,
   frontier flash for result-bearing runs. The comment-classification judge always runs
   on gemini-3.5-flash (temperature 0).
4. No public benchmark covers Azerbaijani/Russian → local calibration required before
   business decisions (§10).

---

## 6. Cost analysis (measured, July 2026)

Measured with `probe_cost.py` (exact billed cost per request from the OpenRouter API):

| Model | $/request | Notes |
|---|---|---|
| google/gemini-3.5-flash | **$0.0072** | ~650 reasoning tokens are mandatory on this endpoint (cannot be disabled; capping is ignored) |
| google/gemini-3.1-flash-lite | **$0.00026** | no reasoning by default; 27× cheaper |

OASIS issues **2–3 LLM requests per agent activation** (action choice → tool result →
final), and the feed grows as comments accumulate. Resulting run costs:

| Run type | Activations | gemini-3.5-flash | flash-lite |
|---|---|---|---|
| `run_smoke.py --demo` (3 posts × ~25) | ~75 | **~$1.3** | ~$0.05 |
| `run_smoke.py` (3 posts × ≤300) | ~900 | ~$16 | ~$0.6 |
| Single full experiment (≤1500 activations) | 1500 | ~$25–40 | ~$1–1.5 |
| Comment classification (~220 comments) | — | **< $0.05** | — |

Built-in cost controls in `run_simulation.py` (all on by default):

- `--max-active` — hard cap on activated agents per step (default 60);
- `--max-calls` — hard budget of activations per run; the run stops early and saves the DB
  (default 1500; smoke series uses 300, demo 25);
- per-step **agent memory reset** (`agent.reset()`, persona survives) — without it CAMEL
  agents resend their entire accumulated history and input tokens grow 6k → 12k → 17k+
  per reactivated agent, dominating the bill (`--keep-memory` to opt out);
- reasoning pinned to minimum; no `max_tokens` in the model config (see §9 pitfalls).

**Always probe an unfamiliar model before a run:** `python probe_cost.py --model <id>` —
one cent, shows exact per-request price, provider and hidden reasoning tokens.

---

## 7. Case study: Birmarket air-conditioner promo

**Injected post** (from the Birmarket brand account, followed by ~35% of agents):

> *"Yayın cırhacırında istilər bizə gəlməmiş, hazırlıqlı ol. Belə ki, IFFALCON
> kondisionerlərini 15 iyuladək düz 45%-dək endirimlə Birmarket.az dan əldə edə bilərsən.
> Sən də sərinliyi evinə gətir, yayı daha rahat keçir. Üstəlik quraşdırma xidməti də
> mövcuddur. Tələs, bu fürsəti qaçırma"*
> (45% off IFFALCON air conditioners until July 15, installation service available.)

Standard test scale: 5 steps, ~280 activations, gemini-3.5-flash, temperature 1.0.

### 7.1 Raw reactions

**61 likes · 0 dislikes · 213 comments · 2 reposts.**
Likes skew to **Q4** (19 of 61 — can afford the purchase, responsive to a 45% discount);
Q1 gives the fewest likes (7) and says why in the comments ("with our electricity prices
any AC is ruin"). All districts and language groups participate; comments come in the
agent's profile language (az 118 / az+ru 64 / ru 31).

### 7.2 Comment classification (213 comments, LLM-judge)

| Sentiment | | Stance | | Intent | | Objection | |
|---|---|---|---|---|---|---|---|
| neutral | 66% | skeptical | 37% | **considering** | **87%** | **trust** | **38%** |
| positive | 25% | support | 23% | buy intent | 7% | price | 35% |
| negative | 9% | question | 21% | no intent | 7% | none | 15% |
| | | worried | 15% | | | quality | 8% |
| | | | | | | availability | 4% |

### 7.3 Sample agent comments (verbatim)

Unedited agent output from the included run DB (`results/demo_ad_gemini-3.5-flash.db`),
with the author's profile and the judge's labels. Agents write in their profile language
(Azerbaijani / Russian / mixed); English glosses added here for the reader.

> **[Q2, 37, Xətai, az]** — *support / considering*
> «Ayda, lap yerinə düşdü bu endirim! Evə kondisioner lazımdır uşaqla bu istidə dözmək
> olmur. Qiymətlər necədir görəsən?»
> *(“Perfect timing for this discount! We need an AC, impossible to bear this heat with a
> kid. I wonder what the prices are like?”)*

> **[Q2, 66, Xətai, az]** — *question / considering* — the installation question, verbatim
> «45% endirim yaxşıdır, amma quraşdırılma pulsuzdur yoxsa əlavə ödəniş tələb olunur?
> Son qiyməti neçəyə başa gəlir?»
> *(“45% off is good, but is installation free or paid extra? What does the final price
> come to?”)*

> **[Q1, 24, Yasamal, az]** — *skeptical / no intent / trust objection* — the fake-discount trope
> «45% endirim yaxşı səslənir amma belə şeylərə çox inanmıram, yəqin qiyməti əvvəlcədən
> şişirdib sonra güya endirim edirlər...»
> *(“45% sounds nice but I don't believe these things — they probably inflate the price
> first and then ‘discount’ it...”)*

> **[Q2, 19, Binəqədi, ru]** — *worried / considering / price objection* — the income constraint
> «Ой, скидка это супер конечно, а то жара в Баку просто нереальная уже(( но цены все
> равно наверное кусаются, с нашими то зарплатами... сколько стоит хоть со скидкой?»
> *(“The discount is great, the Baku heat is unreal already(( but the prices probably
> still bite, with our salaries... how much is it even with the discount?”)*

> **[Q2, 21, Nizami, az]** — *sarcasm / considering / price objection* — the electricity-bill angle
> «Kondisioner yaxşıdı e amma sonra gələn o işıq pulu adamı yandırıcaq 😂 bu isti yayda
> dözmək də olmur»
> *(“The AC is nice, but the electricity bill that follows will burn you alive 😂 though
> this summer heat is unbearable too”)*

> **[Q5, 37, Suraxanı, ru]** — *sarcasm / no intent / trust objection* — high-income cynic
> «Ой да ладно, 45%... Знаем мы эти скидки, сначала цену поднимут, а потом типа скинули.
> Да и установка небось дороже самого кондея выйдет😒»
> *(“Oh come on, 45%... We know these discounts — first they raise the price, then they
> ‘cut’ it. And installation will probably cost more than the AC itself 😒”)*

> **[Q4, 19, Xəzər, az+ru]** — *support / considering* — the young bilingual browser
> «Ого, скидка нормальная такая)) кондиционер в эту жару щас просто спасение, надо
> чекнуть Birmarket.az 🤔»
> *(“Oh, that's a decent discount)) an AC is a lifesaver in this heat, gotta check
> Birmarket.az 🤔”)*

Every campaign insight in §7.4 traces back to comments like these: the installation
question and the price-transparency demand appear across ages and districts; trust
skepticism concentrates in Q1–Q2; sarcasm about inflated discounts and electricity
bills spans income levels.

### 7.4 Campaign insights

1. **The №1 conversion barrier is trust, not price** (38% vs 35%). Agents habitually buy
   electronics from offline chains and hesitate to order an appliance from a marketplace.
   Most-mentioned alternatives: Soliton (28), Kontakt Home (27), BakuElectronics (21),
   Irshad (14), Umico (9). → Creative should lead with official warranty, verified-seller
   status and included installation, not just the discount size.
2. **Price objection falls monotonically with income**: Q1 22 → Q2 17 → Q3 14 → Q4 13 →
   Q5 8 mentions. The economically coherent gradient is a strong internal-validity signal —
   the population "does the math" of its own incomes.
3. **A recurring concrete question: "is installation free or paid separately?"** — asked
   verbatim by several personas. A direct candidate for the ad copy ("quraşdırma pulsuz").
4. **Discount-authenticity sarcasm appears** ("bet they inflated the price first and then
   'discounted' it 😂") — a known local consumer trope the simulation reproduces; a
   "price history" proof point would neutralize it.
5. **The audience funnel is wide but shallow**: 87% considering vs 7% explicit buy intent —
   interest exists, the blockers are trust and installation clarity, not desire.

### 7.5 Content discrimination check (same setup, 3 posts)

To verify the simulation distinguishes content — not just generates generic engagement —
the same population received a positive social news item (minimum pensions/wages +50%)
and a negative one (utility tariffs +40%):

| | Birmarket promo | Positive news | Negative news |
|---|---|---|---|
| Likes | **61** | 42 | 24 |
| Dislikes | 0 | 0 | 1 |
| Comments | 213 | 228 | 224 |
| Reposts | 2 | 4 | **9** |
| Comment sentiment | 66% neutral | 48% positive / 52% *worried* stance | **100% negative** |
| Dominant objection | trust 38% | price 79% ("inflation will eat the raise") | price 98% |

The orderings are the realistic ones: **likes track approval** (promo > good news > bad
news), **reposts track outrage virality** (bad news > good news > promo), and comment
*content* tracks the topic exactly, down to a 66-year-old pensioner asking how to pay for
gas from her pension.

Included sample DBs in `results/` are demo-scale replicas of these three runs
(2 steps × ≤15 agents, ~15 comments each) — same qualitative patterns at 1/10 the cost;
regenerate the full-scale versions any time with `python run_smoke.py` (~$16).

---

## 8. How to read the metrics (validated semantics)

The three-post comparison above establishes what each metric does and does not mean:

| Metric | Meaning | Trust it? |
|---|---|---|
| Likes | approval of the content | ✅ discriminates correctly |
| Reposts | virality / outrage amplification | ✅ discriminates correctly |
| Comment **texts** | sentiment, objections, competitor pull, verbatim questions | ✅ the richest signal (use `classify_comments.py`) |
| Dislikes | — | ❌ dead button (1 press in ~840 activations even on outrage content; an LLM-alignment artifact). Measure negativity from comment texts instead |
| Comment **count** | — | ❌ non-discriminative (~80% of activated agents comment regardless of content — LLM chattiness) |

---

## 9. Known limitations & design decisions

1. **Not calibrated in absolute terms.** Engagement *rates* are inflated (comment rate
   ~80%); use rankings and structure, not raw percentages, until calibration (§10).
2. **Brand-preference lists were removed from personas.** The upstream profile generator
   assigned `preferred_brands` uniformly (~21% of agents per brand — no market-share data
   behind it), and list membership dictated attitude toward any advertised brand
   (72% vs 16% positive sentiment split). Attitudes toward brands now come from the base
   model's world knowledge plus scalar traits. The field is preserved in
   `data/baku_agents_1000.json` and should be re-enabled in `convert_profiles.py` **only
   with real market-share weights** (brand awareness / customer-base data).
   Consequence: competitor-mention volume in §7.2 reflects organic model knowledge of the
   local market; treat competitor *shares* as qualitative.
3. **Choral tendency.** Under a hot topic, comments converge on shared phrasings
   ("prices will rise anyway…"). Partly realistic, partly LLM monoculture; a
   distinct-metric (embedding clustering per post) is on the roadmap.
4. **Dislike button is dead** (see §8) — by design of aligned LLMs, not fixable by prompts
   we tested; the classification pipeline replaces it.
5. **LLM-specific biases**: agents are over-cooperative and over-articulate; sarcasm is
   rarer than in real Baku comment sections (though it does occur and is detected).

---

## 10. Roadmap

1. **Calibration against reality (blocking for business use):** replay 3–5 past Birmarket
   campaigns with known segment-level outcomes; acceptance criterion = the simulation
   reproduces the *ranking* of campaigns and segments. `data/validation/` (real oxu.az
   news corpus) supports the news-side equivalent.
2. Re-enable brand preferences with market-share-weighted sampling (see §9.2).
3. Distinct-metric for choral collapse; comment-rate damping.
4. Longer runs (30 steps) for virality-curve analysis; requires patching OASIS feed
   serialization (comment lists in the prompt grow unboundedly — the last cost frontier).
5. Brand-name normalization in competitor reports (Irshad/İrşad, Neptun/Neptune).

---

## 11. Setup & usage

```bash
pip install -r requirements.txt        # camel-oasis + requests (Python 3.11)
# Windows: set PYTHONIOENCODING=utf-8  (Azerbaijani characters in console logs)
```

An OpenRouter API key is required for simulation and classification. Scripts read
`OPENROUTER_API_KEY` from the environment; `run_smoke.py` prompts for it interactively
if unset.

```bash
# 0. (once) regenerate personas + social graph after any profile/persona change
python convert_profiles.py                     # deterministic, seed 42

# 1. cheapest possible cost check of any candidate model
python probe_cost.py --model google/gemini-3.5-flash

# 2a. demo-scale series (3 posts, ~$1.3 frontier / ~$0.05 lite)
python run_smoke.py --demo --model google/gemini-3.5-flash

# 2b. standard series (3 posts, ~$16 frontier)
python run_smoke.py --model google/gemini-3.5-flash

# 2c. arbitrary single experiment
python run_simulation.py --post "<text>" --poster birmarket|bravo|oxu_az \
    --steps 5 --activation 0.05 --max-active 50 --max-calls 300 \
    --model google/gemini-3.5-flash --db results/my_experiment.db

# 3. demographic reaction report   (post author: birmarket=1000, bravo=1001, oxu_az=1002)
python analyze_results.py --db results/my_experiment.db --post-author 1000

# 4. comment classification (labels cached inside the same DB; reruns are free)
python classify_comments.py --db results/my_experiment.db --post-author 1000
```

One experiment = one new `--db` file; the runner refuses to overwrite an existing DB.

### Operational pitfalls (hard-won — do not rediscover)

| Pitfall | Rule |
|---|---|
| `max_tokens` in the CAMEL model config | **Never set it.** CAMEL treats it as the *total context budget* and silently truncates the agent's persona and feed (at 512 it produced a 100% do-nothing population) |
| `ManualAction` signature | Installed OASIS uses `action_type=` / `action_args=` (online docs show `action=`/`args=` — wrong) |
| Agent memory growth | Reset per step (default behavior); `--keep-memory` multiplies input tokens several-fold |
| Mandatory reasoning | gemini-3.5-flash on OpenRouter cannot disable reasoning (400 error) and ignores token caps; pinned to `effort: low`. Other models get a clean request |
| Windows console | `PYTHONIOENCODING=utf-8`, otherwise cp1252 chokes on ə/ş/ı in logs (cosmetic but noisy) |
| Pasting long Azerbaijani texts into a terminal | Don't — characters get eaten. Post texts belong in files (`run_smoke.py` pattern) |

---

## 12. Reproducibility

- Profile → persona conversion and the social graph are deterministic (`seed 42`).
- Simulation runs use a fixed activation seed (`--seed 42`) but LLM outputs at
  temperature 1.0 vary run-to-run by design; structural findings (demographic gradients,
  objection ranking, metric orderings) replicated across independent runs at both demo
  and standard scale.
- Benchmark reproducibility: fixed subsets and seeds documented in
  `docs/llm_selection_report.md`; benchmark harnesses live in the upstream
  `TwinBench` / `SimBench_release` repositories.
- Every run stores the complete action trace (`trace` table) and all generated content
  in its SQLite DB; classification labels are cached in `comment_labels` inside the same
  file, so a run DB is a self-contained, re-analyzable artifact.
