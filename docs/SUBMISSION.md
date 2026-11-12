# Submission kit

Copy-paste material for the hackathon form. Replace anything in `<angle brackets>`.

## Project name
VoxProof

## Tagline
Say it. Prove it. Pay it. Voice-defined contracts, code-verified AI work, and PayPal payments that are captured only when the proof passes.

## Text description

**The problem.** When you pay an AI service, the service decides when the job is "done." For a small online seller cleaning a supplier catalog, that means a file that looks finished but has invented prices, changed product IDs or dropped rows, and it has already been paid for.

**What VoxProof does.** The customer uploads a messy supplier CSV and says what they need out loud, for example "Preserve all product IDs. Never invent missing prices." An AI turns each spoken sentence into a check from a fixed library that code can run, and shows the customer exactly which sentence became which check. The customer taps Agree, and the contract is hashed.

The customer then authorizes a fixed $5 fee through PayPal (Orders v2, intent AUTHORIZE). The order's `custom_id` is the contract hash, which binds the payment to that exact agreement. An AI worker plans the conversion as a list of allow-listed operations, the server executes them, and an independent verifier (plain Python with no AI, its own parsing rules, reading the files from disk) checks the output against every rule in the contract.

The customer sees each check's result, every failing cell, every changed cell with its original value, and rows flagged for attention. They can ask questions by voice. If everything required passes and the customer taps Accept, the server re-runs the verifier on the exact file, confirms the PayPal order is still bound to the contract, and captures the authorization. If the work fails, the customer rejects it, or the attempts run out, the authorization is voided and the customer pays nothing.

**The trust model.** AI drafts, plans and explains, but it never decides it succeeded and it can never move money. Voice requests like "release the payment" are refused and logged. Capture needs three things at once: the verifier passes, the payment is bound to the contract, and the customer taps Accept.

**Features**
- Push-to-talk voice input and spoken narration (browser Web Speech API)
- AI contract drafting: messy headers mapped to the store schema, spoken sentences turned into code checks, assumptions listed
- Fixed library of 8 code checks: ID preservation, no invented values, schema, row count, price format, integer format, missing-field flags, duplicate-ID flags
- AI worker restricted to allow-listed operations, with automatic retry that feeds back the verifier's findings
- Independent verifier with separately written parsers, enforced by tests
- PayPal sandbox: JS SDK buttons with `intent=authorize`, Orders v2 create/authorize/get, Payments v2 capture/void, idempotency keys
- "Simulate faulty AI worker" demo toggle to show a failure being caught
- Evidence bundle (contract, hashes, plans, reports, PayPal IDs, audit trail) and a downloadable, verified CSV
- Evidence grid built with **AG Grid**: filter to failed / needs-attention / changed rows, search, compare each value with the supplier's original, tooltips with the verifier's reason
- 49 automated tests plus a **Postman** collection (14 requests, 21 tests); runs fully offline in mock mode for judges without keys

## How PayPal is used
- **PayPal JS SDK** (`paypal.Buttons`, `intent=authorize`) for buyer approval.
- **Orders v2**: create order with `intent: AUTHORIZE` and `custom_id` = SHA-256 of the agreed contract; authorize after approval; get order to confirm the binding before capture.
- **Payments v2**: get authorization (validity check), capture (only after verification + Accept), void (on reject or exhausted attempts).
- `PayPal-Request-Id` idempotency keys on every state-changing call. Sandbox only.

## Tools used (AI)
- **<The model you actually used, e.g. Google Gemini (gemini-3.8-flash) via its OpenAI-compatible API, or Claude (claude-sonnet-5-5) via the Anthropic API>**: drafts the contract (column mapping + check selection from a fixed library), plans the worker's operations and gets the verifier's failures as feedback on retry, and answers customer questions about the verification report. All model output is validated server-side; invalid output gets one automatic retry with the validation error.
- **Browser Web Speech API**: speech-to-text for requests and questions; text-to-speech for narration.
- **<Any coding assistant you used while building, if the form asks>**

## Sponsor tools used
- **AG Grid** (Community, MIT): the input preview and the evidence grid. Per-row status, one-click filters (Failed / Needs attention / Changed), quick search, a "Compare with source" toggle that puts the supplier's original value next to each converted value, and highlighted cells whose tooltips give the verifier's exact reason. This is where the customer decides whether to pay.
- **Render**: hosted demo via the included `render.yaml` blueprint.
- **Postman**: `postman/` collection that runs the whole flow with tests, plus direct PayPal sandbox calls (OAuth, AUTHORIZE order, authorize, capture/void).
- **APIMatic** (only if you used it): <describe what you did with the PayPal Context Plugin, e.g. "used it in Claude Code to review our Orders v2 / Payments v2 calls and add …">

## Built during the hackathon
Everything in this repository: backend, verifier, PayPal integration, voice UI, tests and docs.

## Links
- Repo: `https://github.com/<you>/voxproof`
- Hosted demo: `https://<your-app>.onrender.com`
- Video: `https://youtu.be/<id>`
- Judge test login: the PayPal popup needs a sandbox **buyer** account. Either put one in the submission notes (sandbox credentials are test-only, never real), or point judges to `PAYPAL_MODE=mock` for an offline run.

## Final checklist
- [ ] Repo is **public**, `LICENSE` (MIT) at the root, license shown in the GitHub About sidebar
- [ ] Put your name in `LICENSE`
- [ ] `.env` is **not** committed (it's in `.gitignore`), and no keys appear in code or commits
- [ ] README setup steps work on a fresh clone (`pip install -r requirements.txt`, `python run.py`)
- [ ] `python -m pytest -q` passes
- [ ] Hosted URL works with **Sandbox** + real AI pills showing (not MOCK)
- [ ] Demo video **under 3:00**, public on YouTube, shows the app running, no unlicensed music or third-party trademarks
- [ ] Tools section names the exact model you used
- [ ] On Devpost, also tick or list the sponsor tools you used (AG Grid, Render, Postman, and APIMatic if used)
- [ ] Sandbox buyer login or mock-mode instructions given to judges
