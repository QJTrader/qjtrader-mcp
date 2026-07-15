# Releasing `qjtrader-mcp`

Publishing is automated: **push a version tag and GitHub Actions builds and uploads to PyPI** via
[Trusted Publishing](https://docs.pypi.org/trusted-publishers/) (OIDC — no API token stored anywhere),
with an API-token fallback for when OIDC isn't configured yet. Mirrors the `qjtrader` SDK flow.

## One-time setup (per maintainer / repo)

1. **Register the trusted publisher on PyPI.** [pypi.org](https://pypi.org) → account → *Publishing*
   → *Add a pending publisher* (or add it to the project once it exists):
   - **PyPI Project Name:** `qjtrader-mcp`
   - **Owner:** `QJTrader`
   - **Repository name:** `qjtrader-mcp`
   - **Workflow name:** `publish.yml`
   - **Environment name:** `pypi`
2. **Create the `pypi` environment** in the GitHub repo (*Settings → Environments → New environment
   → `pypi`*). Optionally add required reviewers so a human approves each release.

**Current setup:** OIDC Trusted Publishing (active, no stored secret). The trusted publisher is
registered on the PyPI project, so each tagged release uploads with **PEP 740 digital attestations**
(provenance shown on the PyPI project page); the "Select PyPI credential mode" step logs `using OIDC
Trusted Publishing`. Attestations attach at upload time and can't be added retroactively — only
newly uploaded versions gain provenance. If OIDC ever breaks, add a project-scoped `PYPI_API_TOKEN`
repo secret as an emergency fallback (the workflow auto-switches to its "Publish (scoped API token)"
step); remove it once OIDC is restored. To re-register a lost publisher, add it from the project's
own *Publishing* page (a pending publisher is ignored once the project exists).

## Cutting a release

1. Bump the version in `src/qjtrader_mcp/_version.py` (semver).
2. Keep the `qjtrader>=…` floor in `pyproject.toml` at or above the SDK version whose features the
   MCP layer needs (e.g. `prove()`/`chain_stats()` landed in SDK `0.3.1`).
3. Commit, then tag and push:
   ```bash
   git commit -am "Release 0.2.1"
   git tag v0.2.1
   git push origin main --tags
   ```
4. The **Publish to PyPI** workflow builds + uploads. Confirm at
   https://pypi.org/project/qjtrader-mcp/ and test `uvx qjtrader-mcp`.

## If Trusted Publishing fails (OIDC 403 / "not a trusted publisher")

Almost always a **registration mismatch**, not a code problem. Verify the PyPI trusted publisher
matches the table above verbatim (Owner `QJTrader` is case-sensitive; Workflow is the filename
`publish.yml`; Environment `pypi`), that the `pypi` GitHub environment exists, and that the tag was
pushed to `QJTrader/qjtrader-mcp` (not a fork).

**Unblock immediately:** add a project-scoped PyPI API token as the repo secret `PYPI_API_TOKEN`
(*Settings → Secrets and variables → Actions*), then re-run the workflow (it has a
`workflow_dispatch` trigger — no new tag needed). Remove the secret once OIDC is fixed.

## Manual publish (fallback)

```bash
python -m build
python -m pip install twine
twine upload dist/*      # prompts for a PyPI API token
```
