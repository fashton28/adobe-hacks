# CHAMELEON — Submission Rules & Clarifications

*Adobe North America Hackathon 2026 — Pilot Edition*

*This supplements the main challenge brief. Read that first for the overall problem, schema, and difficulty ladder — this document covers specific rules for what happens to your submission and how it's judged.*

---

## Performance

**Latency is not a disqualifying concern.** There is no hard execution-time limit for stage one. A faster engine is preferred, all else equal — "speed and reliability" is a rubric row — but a slower, higher-quality result will not be thrown out just for being slower. Optimize for quality first.

## What gets compared during scoring

Both artifacts your engine produces are evaluated, not just one:

- **The output JSON itself** — checked structurally: same element `id`s as the source (nothing added or removed), required fields present, nothing off-canvas, images kept in proportion, and so on.
- **The rendered PNG** — your output JSON run through the official renderer, then scored by the AI evaluator against the rubric.

A submission with plausible-looking JSON that doesn't actually render legibly doesn't get credit for the JSON, and a rendered image that happens to look fine despite a broken or dishonest JSON doesn't get credit for the image. Both are checked.

## Models and fine-tuning

*(Reading "LORA should be publicly accessible" as: if you fine-tune with LoRA, the adapter must be public — not the "Lora" font used elsewhere in the brand kit. Flag if that's wrong.)*

If your engine relies on a fine-tuned or adapted model — for example, a LoRA adapter on top of an open base model — **the weights must be publicly accessible**: hosted somewhere judges can pull them (e.g. a public Hugging Face repo), not kept private or shared ad hoc. Same spirit as the offline/size-limit rule in the main brief — every team's approach needs to be independently reproducible on the same footing.

## Evaluation hardware

*(Placeholder — "M5 Pro" alone isn't a complete spec. Needs exact core count, RAM, and whether a GPU is available, at the same level of detail as Round 1A's "8 CPUs, 16GB RAM." Filling in with what's stated for now.)*

Stage-one scoring runs on a reference machine: **Apple M5 Pro** *(exact CPU/RAM/disk limits TBD)*. Build and test your engine within that budget — a submission that only runs comfortably on a machine with more headroom than the reference spec risks failing or timing out at actual scoring time.

## Target canvas sizes

Target sizes used in scoring are drawn from a fixed catalogue of common real-world formats, described the way a designer would — e.g. "Instagram Post," "YouTube Thumbnail" — alongside their exact resolution and aspect ratio. This catalogue is one of the "fixed materials" you're allowed to rely on (main brief, Section 5): you can safely assume target sizes will look like real platform formats, not arbitrary rectangles, even though the *specific* hidden targets used at scoring time are ones you won't have seen in advance.

## Adaptive typography and copy — bonus, not required

*(Reading the "diff to judge" flag as: this is allowed, but won't reliably score well automatically, so it's a finale-stage differentiator rather than a stage-one scoring lever.)*

Changing **font size** to help text fit its box is expected — that's core to the problem itself (see the schema example: font size shrinking so a headline wraps to two lines instead of one).

Changing the **font family**, or rewriting/shortening the actual text content, is a different and much harder thing to judge automatically — it touches "faithfulness to the original design's intent," which the rubric weights but wasn't built to fairly score creative rewrites at scale. For **stage-one automated scoring**, treat content and font family as fixed: resize and reposition, don't rewrite. Adaptive typography and copy is exactly the kind of "creativity beyond fitting elements" the main brief calls out for the **finale** (Section 3.3) — a strong direction to explore there, with a live jury who can actually judge it, but not something stage-one's automated rubric rewards.

## Disqualifying: regenerating image content

**Do not regenerate, redraw, or replace the pixel content of any asset — including with generative AI — even for a background or a minor decorative element.** The engine repositions and resizes the elements it's given; it does not invent new imagery. This is the same "no image generation" principle stated throughout the main brief, called out here plainly because it is a **disqualifying violation, not a point deduction**.

If you're ever unsure whether something you're doing counts as "regenerating" versus "resizing," ask before you submit.
