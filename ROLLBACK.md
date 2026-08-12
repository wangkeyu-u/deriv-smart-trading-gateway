# Rollback Guide

This work started from the repository's original default branch and commit:

- Original default branch: `main`
- Original HEAD: `d7659d9a57d6c7ca4a51e874335fc9e58b1f79f2`
- Working branch: `codex/interview-alignment`

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
