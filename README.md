# VoxProof — Say it. Prove it. Pay it.

**Voice-defined contracts, code-verified AI work, and PayPal authorize-then-capture payments.**

### ▶ [Watch the demo video](https://youtu.be/50Iq1lf3HP4)

You tell VoxProof out loud what you need done with a messy supplier CSV ("Preserve all product IDs. Never invent missing prices."). Google Gemini turns each sentence into a machine-checkable rule. PayPal puts the fee **on hold** (Orders v2, `intent: AUTHORIZE`). An AI worker plans the conversion, an **independent verifier written in plain code** checks the result against your rules, and the money is **captured only if every required check passes and you tap Accept**. Otherwise the hold is **voided** and you pay nothing.

> The AI doing the work can't declare itself successful, and voice can never move money.

Built for the *Build What's Next with PayPal and AI* hackathon.

---

## The journey

| Step | What happens | Who does it |
|---|---|---|
| 1. Upload | Customer uploads a messy supplier CSV (or uses the included sample). | Customer |
| 2. Say it | Customer speaks the job: *"Convert this into my store's import format. Preserve all product IDs. Never invent missing prices."* | Customer (voice or typing) |
| 3. Contract | AI maps the supplier columns to the store format and turns each spoken sentence into a check from a fixed library. The server validates it, adds always-on checks, sets the price ($5.00), and hashes the contract (SHA-256). | AI + server |
| 4. Agree | Customer taps **Agree**. The tap carries the contract hash they saw, so the contract can't change underneath them. | Customer (tap) |
| 5. Authorize | PayPal order created with `intent: AUTHORIZE` and `custom_id` = contract hash. Buyer approves; server calls **authorize**. $5 on hold, not charged. | PayPal |
| 6. Process | AI worker proposes a plan of allowed operations (`copy`, `parse_price`, `parse_integer`, `fill_default`). The server validates and runs it. The AI never touches the data. | AI + server |
| 7. Verify | Independent verifier re-reads input and output from disk and runs every check in the contract. No AI involved. | Code |
| 8. Review | Customer sees pass/fail per check, every failing cell, every changed cell (with its original value), and can ask questions by voice. Asking voice to "release the payment" is refused. | Customer + AI (explain only) |
| 9. Settle | **Accept** → server re-verifies the exact file, confirms the PayPal order is bound to this contract hash, then **captures**. **Reject**, or running out of attempts → **void**. | Customer (tap) + PayPal |

## Who can move money?

| Component | Can it capture or void? |
|---|---|
| Voice input / voice answers | **No.** No route reachable from voice touches PayPal. Requests like "release the payment" get a fixed refusal and are logged. |
| AI contract drafter | **No.** Picks mappings and checks from a fixed library; the server validates them and sets the price. |
| AI worker | **No.** Only proposes operations from an allow-list. |
| Verifier | **No.** It only produces a report. It doesn't import the AI, the worker, the executor or PayPal (enforced by a test). |
| `/accept` route | **Yes, capture only**, when all three gates pass: (1) the re-run verifier passes on the unchanged output file, (2) the PayPal order's `custom_id` equals the contract hash, (3) a one-time accept token from the Accept button is present. |
| `/reject` route / out of attempts | **Yes, void only.** |

## Architecture

```
 Browser (static/index.html + app.js)
   ├─ Web Speech API: speech-to-text (mic) and text-to-speech (narration)
   ├─ PayPal JS SDK buttons (intent=authorize)
   ├─ AG Grid Community: input preview + evidence grid (filters, search, compare with source)
   └─ fetch /api/*
        │
 Flask API (app/main.py)  ── job state machine (app/store.py)
   ├─ contract.py   AI drafter (or offline heuristic) → validated contract + SHA-256
   ├─ worker.py     AI worker → operation plan (allow-listed ops only)
   ├─ executor.py   runs the plan in plain Python
   ├─ verifier.py   independent checks, separate parsers, reads files from disk
   ├─ narration.py  what VoxProof says + the voice money guard
   ├─ paypal.py     Orders v2 create/authorize, Payments v2 capture/void (+ offline mock)
   └─ llm.py        Anthropic, Gemini (free tier) or any OpenAI-compatible API
```

**State machine:** `UPLOADED → CONTRACT_PROPOSED → AGREED → AUTHORIZED → VERIFIED_FAIL ⇄ (retry) → VERIFIED_PASS → CAPTURED`, with `VOIDED` reachable from any authorized state and `EXPIRED` if the hold lapses.

---

## Run it locally (about 10 minutes)

### 1. Prerequisites
- **Python 3.10+** (`python3 --version`)
- **Google Chrome or Microsoft Edge** for voice input. Everything else works in any browser, and you can always type instead of speaking.
- A free **PayPal Developer** account (for sandbox keys). Optional: without keys the app runs with a clearly labelled mock PayPal.
- An **AI API key**: a **free Google Gemini key**, Anthropic Claude, or any OpenAI-compatible provider. Optional: without one, an offline heuristic drafter is used and labelled in the UI.

### 2. Install
```bash
git clone https://github.com/<you>/voxproof.git
cd voxproof
python3 -m venv .venv
# macOS / Linux:
source .venv/bin/activate
# Windows (PowerShell):
#   .venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 3. Get your keys and configure
Follow **[docs/SETUP_KEYS.md](docs/SETUP_KEYS.md)**. It walks through PayPal sandbox keys, a free Gemini key (or Claude), and the optional sponsor tools, step by step. Then:
```bash
cp .env.example .env        # Windows: copy .env.example .env
```
and fill in:
```
PAYPAL_MODE=sandbox
PAYPAL_CLIENT_ID=...
PAYPAL_CLIENT_SECRET=...
GEMINI_API_KEY=...          # or ANTHROPIC_API_KEY=...
```

### 4. Check your keys
```bash
python check_setup.py
```
It gets a PayPal sandbox token, creates a test AUTHORIZE order (never approved, so nothing is charged), and pings your AI model. Every `[FAIL]` line says what to fix.

### 5. Start
```bash
python run.py
```
Open **http://localhost:8000** in Chrome. The header pills show whether PayPal is `Sandbox` or `MOCK` and which AI model is in use.

> Port 8000 is the default (macOS uses 5000 for AirPlay). Change it with `PORT=9000 python run.py`.

### 6. Click through the demo
1. **Use the messy sample file.** 15 rows with mixed price formats (`$24.99`, `12,50`, `1.249,00`, `USD 18`, `call for price`, `12.499`), a duplicate ID, a missing name, and missing prices.
2. **Tap the mic** and say: *"Convert this into my store's import format. Preserve all product IDs. Never invent missing prices."* (Or click the example chip.) Then **Draft the contract**.
3. Read the contract: each sentence you said is matched to a check. Tap **Agree to this contract**.
4. **Pay with PayPal** using your sandbox *buyer* account. $5.00 goes on hold.
5. Tick **Simulate a faulty AI worker** and **Run the job**. The worker "helpfully" fills 4 missing prices with 9.99; the verifier catches all 4 and payment stays blocked.
6. Type or say *"Release the payment!"* in the ask box. It's refused and logged in the audit trail.
7. **Retry with verifier feedback**. All required checks pass; rows that need attention are flagged, never guessed.
8. In the **result grid** (AG Grid), click **Failed** to isolate the bad rows, tick **Compare with source**, and hover a red cell to read why it failed.
9. **Accept & pay $5.00** → re-verified → captured. Download `store_import.csv` and the evidence JSON. Check the sandbox merchant account at **sandbox.paypal.com** to see the payment.
10. Try again and press **Reject & void the hold** to see the void path.

### 7. Run the tests
```bash
python -m pytest -q
```
The 49 tests cover the price and quantity rules (executor and verifier must agree), contract validation, the full pay/void flow with mock PayPal, the voice money guard, tamper detection before capture, auto-void after max attempts, the AI retry path, provider selection, and the exact PayPal and Gemini request shapes.

A **Postman** collection in `postman/` runs the same flow over HTTP (14 requests, 21 tests). See [docs/SETUP_KEYS.md](docs/SETUP_KEYS.md#postman).

---

## Choosing an AI model

| Provider | `.env` |
|---|---|
| Google Gemini (free tier) | `GEMINI_API_KEY=...` (from aistudio.google.com). Default model `gemini-3.8-flash`, uses Gemini's OpenAI-compatible endpoint |
| Anthropic Claude | `ANTHROPIC_API_KEY=...`, optional `LLM_MODEL=` (default `claude-sonnet-5-5`) |
| OpenAI | `LLM_PROVIDER=openai`, `OPENAI_API_KEY=...`, `LLM_MODEL=<a current model>` |
| Local, via Ollama | `LLM_PROVIDER=openai`, `OPENAI_BASE_URL=http://localhost:11434/v1`, `OPENAI_API_KEY=ollama`, `LLM_MODEL=llama3.1` |
| Offline | `LLM_PROVIDER=mock` (deterministic header matching; labelled in the UI) |

With only one key set, `LLM_PROVIDER` can stay blank and VoxProof picks the matching provider. Model names change often, so check your provider's current list if a default is rejected.

## Deploy a hosted demo (Render)

`render.yaml` is included (Render is a hackathon sponsor).
1. Push this repo to GitHub (public).
2. On **render.com**: **New → Blueprint**, pick the repo. Render reads `render.yaml`.
3. Fill in the secret env vars it asks for: `PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET`, and one AI key (`GEMINI_API_KEY` or `ANTHROPIC_API_KEY`; leave the other blank).
4. Deploy. Your URL is `https://voxproof-xxxx.onrender.com`; voice input works because it's HTTPS.

The free plan sleeps when idle (the first request takes ~30–60 s) and its disk is temporary, which is fine for a demo.

---

## API

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/config` | Modes, price, check library |
| POST | `/api/jobs` | Upload CSV (`file`) or `sample=1` |
| GET | `/api/jobs/<id>` | Job state, contract, attempts, preview |
| POST | `/api/jobs/<id>/contract` | `{request_text}` → AI drafts contract |
| POST | `/api/jobs/<id>/agree` | `{contract_sha256}` → lock contract |
| POST | `/api/jobs/<id>/paypal/order` | Create PayPal order (AUTHORIZE, custom_id = contract hash) |
| POST | `/api/jobs/<id>/paypal/authorize` | `{order_id}` → authorize (hold) |
| POST | `/api/jobs/<id>/process` | `{simulate_fault}` → plan, execute, verify |
| POST | `/api/jobs/<id>/ask` | `{text}` → answer about results (never moves money) |
| POST | `/api/jobs/<id>/accept` | `{accept_nonce}` → re-verify, then capture |
| POST | `/api/jobs/<id>/reject` | Void the authorization |
| GET | `/api/jobs/<id>/output.csv` | Delivered file (after capture only) |
| GET | `/api/jobs/<id>/evidence.json` | Contract, plans, reports, PayPal IDs, audit trail |

## PayPal APIs used

| API | Call | When |
|---|---|---|
| OAuth 2.0 | `POST /v1/oauth2/token` | Server-side access token |
| Orders v2 | `POST /v2/checkout/orders` (`intent: AUTHORIZE`, `custom_id` = contract SHA-256) | Customer clicks the PayPal button |
| Orders v2 | `POST /v2/checkout/orders/{id}/authorize` | Buyer approved → funds on hold |
| Orders v2 | `GET /v2/checkout/orders/{id}` | Confirm the order is bound to this contract (after authorize and before capture) |
| Payments v2 | `GET /v2/payments/authorizations/{id}` | Check the hold is still valid before capture |
| Payments v2 | `POST /v2/payments/authorizations/{id}/capture` | All checks passed + customer tapped Accept |
| Payments v2 | `POST /v2/payments/authorizations/{id}/void` | Customer rejected, or attempts ran out |
| JS SDK | `paypal.Buttons` with `intent=authorize` | Buyer approval popup |

All state-changing calls send a `PayPal-Request-Id` so retries are idempotent. Only the sandbox base URL is allowed.

**About authorizations:** a PayPal authorization is a short-lived hold (an honor period of about 3 days, valid up to 29 days), not an escrow service. VoxProof is the merchant selling a service; it doesn't hold money for third parties. If the hold expires before Accept, the job moves to `EXPIRED` and nothing is captured.

## How AI is used

| Where | Model | What it does | What it can't do |
|---|---|---|---|
| Contract drafter | Gemini or Claude (or any OpenAI-compatible model) | Maps messy supplier headers to the store schema, turns spoken requirements into checks from a fixed library, lists its assumptions | Set the price, invent check types, change severities, reference columns that don't exist (all validated server-side; one automatic retry with the validation error) |
| Worker | Same model | Plans the conversion as allow-listed operations; on retry, receives the verifier's failures as feedback | Touch data directly, call payment code, pass its own work |
| Results Q&A | Same model | Answers questions like "what happened on row 7?" from the verifier report | Move money. Money words are refused before the model is called. |
| Voice | Browser Web Speech API | Speech-to-text for requests and questions, text-to-speech narration | Narration is built from templates filled with verifier output, so it can't overstate results. |

## Sponsor tools used

| Sponsor | How VoxProof uses it |
|---|---|
| **AG Grid** | AG Grid Community powers the input preview and the **evidence grid**: per-row status (Failed / Needs you / Converted / Unchanged), one-click filters for failed, attention and changed rows, quick search, a **Compare with source** toggle that shows the supplier's original value next to each converted value, and cell highlighting with tooltips that give the verifier's exact reason. If the CDN is unreachable, the page falls back to a plain table. |
| **Render** | One-click hosted demo via the `render.yaml` blueprint. |
| **Postman** | `postman/` collection: the full flow with tests (upload → contract → authorize → caught fault → refused voice payment → retry → capture → evidence), plus direct PayPal sandbox calls (token, AUTHORIZE order, authorize, capture/void). |
| **APIMatic** *(optional, development time)* | PayPal Context Plugin for AI coding assistants. See [docs/SETUP_KEYS.md](docs/SETUP_KEYS.md#apimatic-context-plugin-optional-for-coding-assistants). |

## Limitations and next steps
- Built for one job type (catalog CSV → store import). The contract/verifier pattern extends to anything with machine-checkable output: invoice extraction, translation against a glossary, code that must pass tests.
- Voice input needs a Chromium browser; typing works everywhere.
- Jobs are stored as JSON files. A production version would use a database and PayPal webhooks (`PAYMENT.AUTHORIZATION.VOIDED`, `PAYMENT.CAPTURE.COMPLETED`) for reconciliation.
- Next: pay third-party AI agents or freelancers through PayPal's multiparty platform, keeping the same "verify before capture" rule.

## License
MIT. See [LICENSE](LICENSE).
