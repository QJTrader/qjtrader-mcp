# Security Policy

## Supported versions

The latest release of `qjtrader-mcp` on [PyPI](https://pypi.org/project/qjtrader-mcp/) receives
security fixes. Please upgrade to the latest version before reporting an issue.

## Reporting a vulnerability

**Please do not report security vulnerabilities in public GitHub issues.**

Report privately through GitHub's private vulnerability reporting:

- <https://github.com/QJTrader/qjtrader-mcp/security/advisories/new>

If you cannot use GitHub, reach the QJ Trader team via <https://qjtrader.ai>. We aim to acknowledge
reports within a few business days and will keep you informed as we investigate and ship a fix.

When reporting, please include the affected version, a description of the issue, and (if possible) a
minimal reproduction.

## Verifying release authenticity

Every `qjtrader-mcp` release on PyPI is published straight from this repository's GitHub Actions
workflow via [PyPI Trusted Publishing](https://docs.pypi.org/trusted-publishers/) — **no API tokens,
no manual uploads**. Each release file carries a [PEP 740](https://peps.python.org/pep-0740/) digital
attestation, so you can cryptographically confirm it was built by `QJTrader/qjtrader-mcp` and not
tampered with:

- The **Provenance** section on the [PyPI project page](https://pypi.org/project/qjtrader-mcp/) shows
  the signing GitHub workflow.
- Programmatic verification is available through PyPI's
  [Integrity API](https://docs.pypi.org/api/integrity/).

If a release lacks provenance or its attestation does not resolve to this repository, do not trust
it — please report it via the channel above.
