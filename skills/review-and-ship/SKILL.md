---
name: review-and-ship
description: "Implement a repository change, run independent review-agent cycles until no P0/P1 findings remain, and publish or update a pull request. Use only when explicitly invoked with an implementation request."
---

# Review and Ship

Take all text following `$review-and-ship` as the implementation request.

## Input and authority

- If the invocation contains no implementation request, ask for one and stop.
- The input authorizes only the repository changes, validation, commit, push, and pull-request
  publication needed to complete that request.
- Do not expand the request into unrelated cleanup, issue creation, deployment, merging, destructive
  Git operations, or other external changes.

## Prepare

1. Read every applicable `AGENTS.md` and any skill required by the request.
2. Inspect the relevant implementation, tests, and call sites before editing. Resolve discoverable
   facts from the repository; ask only when a missing product decision materially changes the work.
3. Isolate the requested work on an isolated environment/worktree, and stop for user direction if overlapping edits cannot be separated safely.

## Implement and validate

1. Implement the requested behavior with the smallest coherent change.
2. Add or update focused regression coverage where it provides meaningful confidence.
3. Run the relevant focused checks and repository gates. Record exact results and distinguish
   failures introduced by this change from confirmed pre-existing failures and unclassified
   failures.

## Review loop

1. Delegate a fresh, independent, read-only review of the complete current change using
   `$review-agent`. Give the reviewer the exact target and comparison base needed to inspect the
   change that would merge.
2. Record every finding and its priority.
3. Fix every P0 and P1 finding related to the requested work, then rerun the affected validation.
4. After any fix, request another fresh `$review-agent` review of the complete updated change, not
   only the latest fix.
5. Repeat until the latest review reports no P0 or P1 findings related to the work.

P2, P3, and lower-priority findings do not block publication. Do not fix them unless the user
separately requests it or the fix is required to resolve a P0/P1. Retain every lower-priority
finding for the final report, including one that is incidentally resolved by a later high-priority
fix, and state its final disposition.

If a P0/P1 cannot be resolved without broadening scope, obtaining missing authority, or making a
material product decision, stop before publication and report the exact blocker. Never weaken or
skip the review gate.

## Publish

Publish only after the implementation is complete and the review gate is clear.

1. Review the final diff and stage only files belonging to the requested work.
2. Commit with a concise repository-appropriate message and push the head branch.
3. Reuse an existing open pull request for the head branch instead of creating a duplicate.
4. Otherwise create a non-draft pull request when relevant validation passes.
5. Create a draft pull request when P0/P1 clearance is achieved but an external limitation or a
   demonstrably pre-existing validation failure prevents review-ready status. Explain that
   limitation in the pull request.
6. Include a concise summary and validation evidence in the pull-request body. Do not expose
   secrets, private repository information, or non-portable local filesystem paths.

If authentication, network access, or repository permissions prevent pushing or creating the pull
request, preserve the completed local work and report the failed publication step and evidence.
Never merge the pull request.

## Final handoff

Report:

- the pull-request link and whether it is ready or draft, or the exact publication blocker;
- what was implemented;
- validation commands and outcomes, including any pre-existing or unclassified failures;
- the number of independent review cycles and explicit confirmation that no P0/P1 findings remain;
- every P2, P3, or lower-priority finding with its location, impact, and final disposition, or
  explicitly state that none were raised;
- any remaining test gaps or residual risks.
