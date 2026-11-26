# Evals

Behavioral evals for the `harvest` skill, run with
Claude Code's `claude plugin eval`. They use your own Claude
credential and cost tokens, so they are not part of CI.

```bash
claude plugin eval . --scaffold --allow-tools 'Bash(python3:*)' --runs 3
```

| Case | Checks |
|---|---|
| `harvest-quality` | good trigger questions, only shareable lessons, no secrets, skips trivia, asks first |
| `harvest-nothing-to-keep` | an uneventful session produces no lessons |
| `harvest-no-store` | without a store it points to `/stickit init` and stops |

`--scaffold` runs `scaffold-store.sh` to create an empty store for the cases
that need one. Results land in `evals/results/` (gitignored).
