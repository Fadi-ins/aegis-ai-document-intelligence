# Reporting a security issue

Use the repository’s **Security → Report a vulnerability** option when available. Include the affected commit, the expected access boundary, and the observed behavior using synthetic documents. If private reporting is unavailable, open a public issue asking the maintainer for a private reporting channel. Keep credentials, private PDFs and sensitive details out of public issues and Actions logs.

The maintained version is the current `main` branch. Aegis is intended for local use. The default Docker deployment binds the API to loopback and keeps PostgreSQL off the host network. Use the Linux container profile for untrusted PDFs.
