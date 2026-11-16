# Reporting a security issue

Use the repository’s **Security → Report a vulnerability** option when available. Include the affected commit, the expected access boundary, and the observed behavior using synthetic documents. If private reporting is unavailable, open a public issue asking the maintainer for a private reporting channel. Keep credentials, private PDFs and sensitive details out of public issues and Actions logs.

The maintained version is the current `main` branch. Aegis is intended for local use. The default Docker deployment binds the API to loopback and keeps PostgreSQL off the host network. Use the Linux container profile for untrusted PDFs.

## GitHub owner settings

To activate and check the repository settings, run the following from an updated clone using the GitHub CLI signed in to the repository owner account:

```sh
gh auth login
python scripts/enable_github_security.py
```

The script verifies each change, preserves existing rulesets, and reports any setting GitHub rejects. The main branch rules require a pull request, resolved review discussions, up-to-date passing checks and CodeQL results. The single-maintainer setup permits merging your own passing pull request. It also blocks deleting or force-pushing the branch.
