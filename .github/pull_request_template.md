Thank you for your contribution! All PRs should include the following sections. PRs missing these sections may be closed immediately.

## Short description

This PR... *[fill here]*

## AI Disclosure

We encourage the use of AI tooling in creating PRs, but the any non-trivial use of AI needs be disclosed. E.g. if you used Claude to write a first draft, you should mention that. Trivial tab-completion doesn't need to be disclosed. **You should self-review all PRs, especially if they were generated with AI**. 

-----

- [ ] I used AI to... *[fill here]*
- [ ] I did not use AI

----

## Type of Change

- [ ] Bug fix
- [ ] New feature (non-breaking)
- [ ] New feature (breaking change)
- [ ] Documentation update
- [ ] Test improvements

## Related Issues

If this PR closes an issue, please link it below: 

Closes: 

## Testing and linting

Please run tests before submitting changes:
   ```bash
   python -m pytest
   ```

and format your code using Ruff:

   ```bash
   ruff check --fix --select I && ruff format
   ```
