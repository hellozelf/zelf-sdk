## What changed

<!-- One or two sentences. What the reader needs to know before the diff. -->

## Why

<!-- The problem this solves. Link the issue if there is one. -->

## Generated code

These clients are generated. Source changes go in `codegen/`, never in a
language directory, because `make all` rewrites those.

- [ ] Changed the emitter or template, not the output
- [ ] Ran `make all`, and the regenerated files are in this PR
- [ ] `git status` is clean after a second `make all`

## Checks

- [ ] `make test` passes
- [ ] New behaviour has a test that drives it, not just one that imports it
- [ ] Docs updated if the public surface moved

## Affected languages

<!-- Tick what this touches. A spec change touches all seven. -->

- [ ] Python
- [ ] TypeScript
- [ ] Go
- [ ] Rust
- [ ] Ruby
- [ ] Java
- [ ] C#
