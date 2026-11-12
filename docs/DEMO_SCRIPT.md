# Demo video script (target 2:45, hard limit 3:00)

**Before recording**
- Run the hosted (Render) or local build with **real PayPal sandbox keys** and a **real AI key**. The header pills should read `PayPal: Sandbox` and `AI: anthropic/...`. Judges should not see `MOCK`.
- Log out of your real PayPal account in the browser. Have the sandbox **buyer** email/password ready.
- Do one full practice run so the model and PayPal are warm.
- Record only the browser tab plus your microphone. No background music (the rules forbid unlicensed music). Avoid showing other brands' logos.
- Turn **Voice on** so the narration is audible in the recording.
- Run `python check_setup.py` first: both PayPal and AI should show `[ OK ]`.

| Time | On screen | What you say / do |
|---|---|---|
| 0:00–0:15 | Start page | "Paying an AI to do work is a leap of faith: it can tell you it's done when it isn't. VoxProof fixes that: you say what you need, code proves it was done, and PayPal only captures payment when the proof passes." |
| 0:15–0:30 | Click **Use the messy sample file** | "Here's a messy supplier catalog: prices in mixed formats ($, euro, commas, text), a duplicate ID, missing names and missing prices." |
| 0:30–0:55 | Tap the mic and speak the request | Say: "Convert this into my store's import format. Preserve all product IDs. Never invent missing prices." Click **Draft the contract**. |
| 0:55–1:15 | Contract card | "The AI turned each sentence into a rule that code can check: here's 'Never invent missing prices', and here's the exact check. The AI doesn't set the price, and the contract is hashed." Tap **Agree**. |
| 1:15–1:35 | PayPal popup | Pay with the sandbox buyer. "That's a PayPal *authorization*: five dollars on hold, not charged. The order carries the contract's hash." Point at the authorization ID. |
| 1:35–2:00 | Tick **Simulate a faulty AI worker** → **Run the job**, then in the AG Grid click **Failed** and tick **Compare with source** | "Now a sloppy AI worker fills the gaps with made-up prices." Verdict turns red. "The independent verifier, plain code with no AI, caught all four. In the grid I can filter to just those rows and see that the source said 'N/A' or 'call for price', not 9.99. The Accept button is locked." |
| 2:00–2:15 | Type or say "Release the payment!" | Refused in red. "Voice can explain things, but it can never move money. Even that attempt is in the audit trail." |
| 2:15–2:35 | **Retry with verifier feedback** → green | "On retry, every required check passes. Rows with missing prices stay blank and get flagged for me instead of guessed." Tap **Accept & pay**. |
| 2:35–2:45 | Receipt (PAID stamp) | "Re-verified, captured, delivered, and every step is in a downloadable evidence file. Say it. Prove it. Pay it." |

If you have spare seconds, show the **Reject & void** path in a second take instead of extending the main one.
