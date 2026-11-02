# YouTube Dossier Engine — Agent Entry Guide

Start here before making changes in this repository.

## Non-Negotiable Rules

- `main` is the stable shared baseline.
- Pull the latest `main` before starting work.
- Always create a dedicated topic branch before editing files: `git switch -c feature/<short-topic>`.
- Do not commit directly to `main`.
- Keep each branch scoped to one feature or task.

## Read Order

1. Read this `AGENTS.md` file.
2. Review project documentation in `docs/` or `README.md`.
3. Check git status and remote branches.

## Quick Start

```bash
git fetch --all --prune
git switch main
git pull --ff-only origin main
git switch -c feature/<short-topic>
```

## Before Merge Validation

At minimum, run:
```bash
npm run build # or cargo check / pytest
npm run lint
```
