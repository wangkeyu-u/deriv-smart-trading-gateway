# Rollback Guide

This work started from the repository's original default branch and commit:

- Original default branch: `main`
- Original HEAD: `d7659d9a57d6c7ca4a51e874335fc9e58b1f79f2`
- Working branch: `codex/interview-alignment`
- Round 1 HEAD: `101ca58ec53db457b01db57ba6a125c66f6f7f51`
- Local round 1 tag: `codex/round1-complete`

No history on `main` is rewritten. No force push or normal push is part of this
work.

## Return to the original code

From this repository, switch back to the original branch and verify its commit:

```bash
git switch main
git rev-parse HEAD
```

The second command should print:

```text
d7659d9a57d6c7ca4a51e874335fc9e58b1f79f2
```

## Delete the local working branch

After switching to `main`, delete the interview-alignment branch:

```bash
git branch -D codex/interview-alignment
```

This removes only the local working branch. The original `main` branch and its
recorded commit remain unchanged.

## Return only to the completed round 1 state

The annotated local tag `codex/round1-complete` records the repository exactly
as it was after round 1. To keep the current branch name and move it back to
that state, first make sure any round 2 work you want to retain is committed,
then run:

```bash
git switch codex/interview-alignment
git reset --hard codex/round1-complete
git rev-parse HEAD
```

The last command should print:

```text
101ca58ec53db457b01db57ba6a125c66f6f7f51
```

For a non-destructive inspection that does not move the working branch, create
a separate local branch from the tag instead:

```bash
git switch -c codex/round1-review codex/round1-complete
```

The tag is local only and is not pushed by this work.
