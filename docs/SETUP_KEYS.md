# Getting your keys (about 15 minutes)

VoxProof needs **PayPal sandbox keys** (required) and **one AI key** (pick one). Sponsor tools are optional and need no keys, except a free Postman or Render account if you use them.

> Keys go only in your local `.env` file or in Render's environment settings. Never paste them into GitHub, chat, screenshots or the demo video. If one leaks, regenerate it in the dashboard it came from.

---

## 1. PayPal sandbox keys (required)

Sandbox is PayPal's test environment and uses fake money. You get:
- a **Client ID** and **Secret**, used by the server and the PayPal button
- a **sandbox buyer login**, used in the PayPal popup during the demo

### Steps
1. Go to **developer.paypal.com** and log in. If you don't have one, sign up for a free PayPal account first.
2. **Create a US sandbox seller (business) account.** Go to **Testing Tools → Sandbox Accounts → Create account**, choose **Business** and set **Country/Region: United States**.
   *Why:* VoxProof charges in USD with authorize-then-capture. The default sandbox accounts are created for your home country, which can have currency or feature restrictions. A US account avoids that.
3. **Create a US sandbox buyer (personal) account** the same way, choosing **Personal** and **United States**.
4. Go to **Apps & Credentials** and make sure the toggle at the top says **Sandbox**. Click **Create App**:
   - App name: `VoxProof`
   - Type: **Merchant**
   - Sandbox account: the **US business** account from step 2
5. On the app page, copy the **Client ID**. Click to reveal the **Secret** and copy it too.
6. Get the **buyer login**: go to **Testing Tools → Sandbox Accounts**, click the US **Personal** account (or `⋯` → *View/Edit account*), and note its email and password. You can set your own password there.
7. Add the keys to `.env`:
   ```
   PAYPAL_MODE=sandbox
   PAYPAL_CLIENT_ID=paste-client-id-here
   PAYPAL_CLIENT_SECRET=paste-secret-here
   ```
   No quotes and no spaces around `=`.

**See the money move:** log in at **sandbox.paypal.com** with the sandbox *business* account and open Activity. Authorizations, captures and voids show up there.

---

## 2. AI model key (pick one)

### Option A: Google Gemini (free tier, easiest)
1. Go to **aistudio.google.com** and sign in with a Google account.
2. Click **Get API key → Create API key** and copy it.
3. Add it to `.env`:
   ```
   GEMINI_API_KEY=paste-key-here
   ```
   Leave `LLM_PROVIDER` blank. VoxProof picks Gemini automatically when it's the only key. The default model is `gemini-3.8-flash`; if your account lists a different model, set `LLM_MODEL=` to it. The free tier has rate limits, which is fine for a demo.

### Option B: Anthropic Claude (needs paid API credits)
1. Go to **console.anthropic.com**, then **Settings → API Keys → Create Key**.
2. Add credits under **Billing**.
3. `.env`: `ANTHROPIC_API_KEY=paste-key-here` (default model `claude-sonnet-5-5`).

### Option C: OpenAI or any OpenAI-compatible API
`.env`: `LLM_PROVIDER=openai`, `OPENAI_API_KEY=...`, `LLM_MODEL=<a current model>`, and `OPENAI_BASE_URL=...` for Groq, OpenRouter, Ollama, etc.

If you set more than one key, the order of preference is Anthropic, then Gemini, then OpenAI. Set `LLM_PROVIDER` to choose one explicitly.

---

## 3. Check everything works
```bash
python check_setup.py
```
You should see:
```
PayPal
[ OK ] Sandbox access token received.
[ OK ] Test order XXXXXXXX created with intent AUTHORIZE (5.00 USD). It is never approved, so nothing is charged.
AI model
[ OK ] gemini/gemini-3.8-flash replied: {'ok': True}
All set. Run:  python run.py   and open http://localhost:8000
```
Each `[FAIL]` line tells you what to fix.

---

## 4. Hosted demo on Render
In the Render dashboard, open your service → **Environment** and add the same variables (`PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET`, and `GEMINI_API_KEY` or `ANTHROPIC_API_KEY`). Render redeploys automatically.

---

## 5. Sponsor tools

Using sponsor tools is optional; the rules say any AI tool works. Several sponsors have their own prizes, though, so VoxProof uses the ones that fit naturally.

| Sponsor | Used for | Key needed? | What to do |
|---|---|---|---|
| **AG Grid** (Best Use of AG Grid: $5,000 / $2,000 / 3 × $1,000) | The input preview and the evidence grid: filter by Failed / Needs attention / Changed, search, "Compare with source" columns, highlighted cells with tooltips explaining each failure | No (Community edition, MIT, loaded from CDN) | Nothing, it's built in. Show it in the video. |
| **Render** (Best Use of Render: credits) | Hosting the live demo (`render.yaml` blueprint) | Free Render account | README → *Deploy a hosted demo* |
| **Postman** | Ready-made collection that runs the full flow (14 requests, 21 tests) plus direct PayPal sandbox calls | Free Postman account | See below |
| **APIMatic** (Best Use of APIMatic: 3 × $1,000) | Optional, at development time: the PayPal Context Plugin gives your AI coding assistant accurate PayPal SDK and API context | No key (Node.js 18+) | See below. Only claim it if you actually use it. |

### Postman
1. In Postman, click **Import** and select both files in the `postman/` folder.
2. Choose the **VoxProof Local** environment at top right. Keep `baseUrl` as `http://localhost:8000`, or use your Render URL.
3. Start the server in mock mode for a fully automatic run (real PayPal needs a buyer to click Approve in a browser):
   ```bash
   PAYPAL_MODE=mock python run.py          # Windows PowerShell: $env:PAYPAL_MODE="mock"; python run.py
   ```
4. Right-click folder **1. VoxProof flow** → **Run folder**. All 21 tests should pass.
5. Folder **2. PayPal sandbox direct** calls PayPal's APIs directly. Fill `paypal_client_id` and `paypal_client_secret` in the environment, run **A** and **B**, open the approve link printed in the Postman console, approve with the sandbox buyer, then run **C**, **D**, and **E1** (void) or **E2** (capture).

### APIMatic Context Plugin (optional, for coding assistants)
If you build with Claude Code, Cursor or VS Code Copilot, install the PayPal plugin in your project folder:
```bash
npx context-plugins install paypal
```
In Claude Code you can instead run:
```
claude plugin marketplace add context-plugins/plugin-marketplace
claude plugin install paypal@context-plugins
```
Then give your assistant a real task with it. For example: *"Using the PayPal context plugin, review app/paypal.py against the official Orders v2 and Payments v2 specs, and add a reauthorize step for authorizations older than the 3-day honor period."* In your submission, describe exactly what you did with it.
