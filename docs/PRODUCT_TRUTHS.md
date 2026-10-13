# Product Truths

Hand-written, engineer-approved answers to the questions marketers ask most.

**This file is the highest-priority content in the index.** Retrieval boosts
`doc_type='truth'` above everything else, so a fact here beats a contradicting sentence
elsewhere in the docs.

**How to use this file**

1. Delete the examples below and replace them with real facts about your product.
2. One `## ` heading per question. Keep each answer to three lines or fewer.
3. The `**Source:**` line must point at a file that exists in an allow-listed repo.
4. `**Owner:**` is the team or person a marketer should be told to ask.
5. Never write a fact that no engineer has confirmed. This file is the answer to
   "how do I know what is true?", so an unverified line here is worse than a gap.

**Format**

```markdown
## The question a marketer will ask

**Answer:** two or three short lines, in plain language, with the numbers.
**Source:** docs/file.md
**Owner:** team-name
```

**Review cadence:** re-read this file monthly. Anything that is no longer true must be
corrected or deleted in the same week - a stale truth outranks fresh documentation.

---

## Template: delete everything below this line

## Does the product support single sign-on?

**Answer:** Replace with the real answer, including which plans.
**Source:** docs/auth.md
**Owner:** platform-team

## What is the API rate limit?

**Answer:** Replace with the real number and how it is counted.
**Source:** docs/limits.md
**Owner:** platform-team

## Is there an on-premise version?

**Answer:** Replace with the real answer. If the answer is no, say no plainly and add
"do not promise an exception".
**Source:** README.md
**Owner:** product-leadership