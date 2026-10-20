# Security

## Reporting a vulnerability

Email security@hellozelf.com. Do not open a public issue.

Include the version, the language, and the smallest reproduction you have. We
will confirm receipt within two working days.

## Supported versions

The latest minor release receives security fixes.

## Scope

These are API clients. The most likely findings are in signature verification
(`webhooks.verify`), in how the API key is carried, or in path parameter
encoding. Each client has tests covering all three, and a report that breaks
one of those tests is especially welcome.
