# AI tool disclosure standard

**Overview:** we use AI tools and we say so, precisely. Each author discloses in the first person, names every tool used, states what the tool mechanically did, and states what the author verified. The point of the disclosure is accuracy, not ceremony: what happened, stated plainly, and it stops there.

## The standard

Every disclosure, short or long, carries these elements:

1. First person, per author. "I used", not "AI was used".
2. Name every tool actually used. Do not underdisclose.
3. What the tool mechanically did (drafted a function, explained an error, restructured a section).
4. What the author changed or verified.
5. The affirmation: the methodology, claims, and conclusions reflect the author's own understanding of the material.

## Short version (PR descriptions)

Put this in the PR description whenever AI touched the change:

> AI use: I used <tool> to <what it did>. I <what you changed or verified>, and the result reflects my own understanding.

Example:

> AI use: I used Claude to draft the retry wrapper in tools/news.py and explain the tenacity API. I rewrote the backoff parameters, added the test for the give-up path, and verified the behavior against the tenacity docs.

## Long version (the final notebook)

Each author writes their own paragraph in the notebook's disclosure section, first person, following the same five elements, with a proper in-text citation and a reference entry. Example form:

> I used Claude, a large language model developed by Anthropic (Anthropic, 2026), as a tool to aid my understanding of the course material. It <what it mechanically did>. I have reviewed, modified, and verified all AI-generated content against the cited sources, and the methodology, claims, and conclusions presented reflect my own understanding of the material. <Ownership claims: the substantive arguments, design choices, and interpretations that are the author's own.>

Reference entry (APA 7, alphabetized with the others):

> Anthropic. (2026). *Claude* (Fable 5.1) [Large language model]. https://claude.ai

Name the actual tool and version used; the entry above is the format, not a fixed answer.
