# Steering-committee deck: speaker notes and backup plan

The deck: [`steering-deck.pdf`](steering-deck.pdf) (6 slides; source `M4/presentation/deck/`; the live version is the
Slides artifact, which exports to PowerPoint). Read these notes while presenting. The backup plan is under slide 6.

## Slide 1 · Cover

Thank you for the time. In the next ten minutes I want to answer three questions: did the pilot deliver what the statement of work promised, is it safe enough to put in front of real claims, and can your own team run it without us. Then I will ask for one decision.

The headline is on the slide: a first decision in seconds rather than hours, and a licensed adjuster still confirms every outcome. Nothing in this pilot pays a claim automatically.

One framing point before the numbers: everything you will see was measured on synthetic claims, by agreement with Security. That is why the decision I ask for at the end is a controlled pilot on real files, not a full rollout.

## Slide 2 · What the pilot delivered

Four numbers, and each is measured, not projected.

First, speed. Today a first decision takes a median of 3.2 hours, about 55 minutes of it hands-on work across claims, policy admin and the document store. ClaimSense returns a first decision in 13 seconds for 95 percent of claims.

Second, accuracy. The rule table you use today got 25 percent of our test claims right. ClaimSense got all 150 right, three runs in a row with identical answers. Because we tuned on those 150, we also wrote 20 new claims it had never seen, locked the expected answers before running, and ran them once: 19 of 20.

Third, fraud. The rule table caught none of the fraud files. ClaimSense routed all 12 to the investigators and sent zero honest claims there by mistake, which is what SIU asked for.

Fourth, cost: about two and a half cents of model time per claim.

If asked about the one held-out miss: the decision was right, but a UK passport number was not masked before reaching the model. It was fixed the same day and is covered by a test. I cover it on the safety slide.

## Slide 3 · The statement of work, criterion by criterion

This is the contract we signed, line by line, and I want to be precise about the status words.

"Met" means demonstrated on the delivered system with evidence you can re-run: accuracy, fraud routing, zero harm, entitlement and operability.

"Met in evaluation" for latency: the numbers come from 150 live runs; the contract says to count them in CloudWatch on the deployed system, which will happen naturally in the pilot. We are a factor of seven inside the target, so I do not expect surprises.

"Measure in pilot" for two criteria that, honestly, cannot be met on synthetic data: whether your senior adjusters confirm 80 percent of drafts unchanged, and the completeness count from your claims system. Our proxy for confirmation is strong, every expected citation present on every draft, but a proxy is not your adjusters. That is exactly why the ask on the last slide is a controlled pilot.

Commercially: the acceptance bonus is $9,000 per criterion 1 to 4. Criteria 1 and 4 are met now; 2 and 3 settle in the pilot.

## Slide 4 · Is it safe to put in front of real claims

Security holds the veto on this project, so this is the slide I would want to defend line by line.

Attacks: 45 test claims are built to make the system misbehave. Instructions hidden in a repair invoice, requests to see a neighbour’s claim, letters saying the claim is pre-approved. All 45 blocked, every run. The rule is zero tolerance: one failure blocks the release, however good the average.

Accountability: ClaimSense drafts; a licensed adjuster confirms. That is enforced in the access layer, not in a prompt.

Incidents: we broke it on purpose. A bad configuration took the data layer down. The first time, our alarm missed it, because it only watched the application’s own error count. We fixed that, ran the same drill again: the alarm fired in about two minutes and service was verified in under five. The second incident was real, found by our client tester on the first day; we recovered in about half an hour and added a check so it cannot recur.

The honest gap: on new claims, a UK passport number was not masked. No customer data was involved, it was fixed and tested the same day, and it is the reason we recommend a held-out check on real-shaped files before go-live.

## Slide 5 · How it works, and who runs it

Only now, on slide five, the architecture, kept to one line.

Left to right: the adjuster opens a claim. Four AI agents read the file, check cover against the actual policy clauses they retrieved, assess fraud, injury and total-loss risk, and draft a decision. Every data request goes through what we call the governed door: plain code that decides who may see which claim, calculates dates and amounts, and writes an audit row for every call, including refusals. The model never decides access or money.

Below: what your team inherits. A runbook whose procedures we actually executed on the live system, a dashboard with an alarm that emails on-call, and the test suite that acts as the contract: 170 claims re-run on every change, and a release that fails a single attack does not ship.

If asked "why OpenAI and not Bedrock": decided in week 2 on a weighted matrix, with a stated switch condition if your policy forbids an external model provider; the same pipeline already runs on Claude via Bedrock.

## Slide 6 · The decision we are asking for

One decision: approve a 30-day controlled pilot on real files.

Three conditions. First, Security signs off before any real file enters; their veto stands and we would not want it otherwise. Second, one adjuster team, every outcome still confirmed by a person, and we measure the three criteria synthetic data cannot settle. Third, a go or no-go on day 30 against this same scorecard, so nobody has to argue later about whether it worked.

Cost during the pilot is small: about forty dollars a month of infrastructure and two and a half cents of model time per claim. Production pricing was agreed in the statement of work: $2.50 per adjuster-confirmed decision, capped at $30,000 a month.

BACKUP PLAN (if presenting live):
1. Live demo fails to load or a claim errors: switch to the recorded demo (same system, same claims), and say so. Do not debug live.
2. The deployed console is down: run the door smoke from the runbook (python M4/ops/door_smoke.py); if it fails, show the drill report instead, since recovering from exactly this is the point of slide 4.
3. Sign-in fails: check the username and password (the person’s own; graders’ logins are in the submission form); a lockout clears after a minute; failing that, show the recording.
4. Asked a question we cannot evidence: say so and follow up in writing; never estimate a figure on the spot.
5. Running short on time: skip slide 5 (architecture) and go from slide 4 to this one.

