<!--
Thanks for contributing to Sandroid AI Video!
Keep the PR focused and fill in the sections below.
-->
## Summary

<!-- What does this PR do, and why? One or two sentences. -->

## Related issue

<!-- e.g. Closes #12, Relates to #34 -->

## Type of change

- [ ] Bug fix (non-breaking)
- [ ] New feature (non-breaking)
- [ ] Breaking change (existing behavior changes)
- [ ] Refactor / internal cleanup
- [ ] Documentation
- [ ] CI / build / tooling

## Testing

<!-- How did you verify this? Paste commands + results. -->

```bash
# backend
cd backend && ../.venv/bin/python -m pytest -q

# ui
cd ui && npm run build
```

## Checklist

- [ ] Backend tests pass (`cd backend && ../.venv/bin/python -m pytest -q`)
- [ ] UI builds (`cd ui && npm run build`)
- [ ] Python stays compatible with **3.10** (production target: PRoot 3.10.12)
- [ ] No secrets, API keys, tokens, or tracebacks are logged or exposed
- [ ] Docs updated (README / `docs/API.md`) if behavior or the API changed
- [ ] No `data/`, `.env`, or `ui/node_modules/` files are committed

## Screenshots / notes

<!-- Optional: UI changes, migration notes, follow-ups. -->
