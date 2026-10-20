# Contributing

Every language directory is generated. Editing one by hand works until the next
`make all` deletes it.

## Layout

```text
VERSION             one version for all eight clients
spec/openapi.yaml   the published spec, the only input
fixtures/           response examples and model samples, shared by every suite
Makefile            make all | make test | make cov | make <lang>
codegen/            the generator
  spec.py           spec/openapi.yaml -> an intermediate representation
  models.py         the shared model IR the five newer emitters render
  samples.py        a deterministic sample value per model and per type
  naming.py         casing rules and the two spec workaround tables
  models_input.py   prepares the schema document the Python models come from
  downgrade.py      3.1 -> 3.0 rewrite, needed only by the Go toolchain
  make_fixtures.py  writes fixtures/fixtures.json
  emit_*.py         one per language
  emit_conformance.py  the generated test suites
  release.py        reads VERSION
  templates/        the hand written runtime each client is built around
python/ js/ go/ rust/ ruby/ csharp/ java/ php/
```

## Commands

```text
make all          regenerate every client
make rust         regenerate one of them
make test         run all eight suites
make cov          run the suites that gate at 100% coverage
```

## Generated and hand written

Three languages get their types from an off-the-shelf generator:
Python from datamodel-code-generator, TypeScript from openapi-typescript, Go
from oapi-codegen. The other five render `codegen/models.py`'s shared model IR,
which was less work than wiring up five more toolchains.

The request layer, the client, the resources and the conformance suites are
emitted for all eight. The runtime each client is built around lives in
`codegen/templates/` and is copied verbatim.

**Every emitter deletes its output directory and rewrites the build manifest
from a Python string literal.** Config added to a manifest by hand does not
survive:

| File | Written by |
|---|---|
| `python/pyproject.toml` | `emit_python.py` |
| `js/package.json`, `tsconfig.json`, `.prettierrc` | `emit_ts.py` |
| `rust/Cargo.toml` | `emit_rust.py` |
| `ruby/zelf.gemspec` | `emit_ruby.py` |
| `csharp/src/Zelf.csproj` | `emit_csharp.py` |
| `java/pom.xml` | `emit_java.py` |
| `php/composer.json`, `autoload.php` | `emit_php.py` |
| `go/oapi-codegen.yaml` | `emit_go.py` |

What survives: every test directory, `csharp/tests/Zelf.Tests.csproj`,
`java/src/test/`, `go/*_test.go`, `go/go.mod`, the per-language READMEs and
this file.

Generated source is committed. The `codegen` CI job runs `make all` and fails
if the tree is dirty, which is what proves the committed output matches the
spec.

## The envelope

Every 2xx response is wrapped:

```json
{"log_id": "...", "timestamp": "...", "results": [], "item_count": 0,
 "page": 1, "next": null, "previous": null}
```

A stock generator sees one anonymous schema per operation and emits a class for
each. `codegen/spec.py` recognises the envelope instead and collapses it into a
single generic `Page<T>`, so the clients expose the item type and nothing else.
It rejects any operation whose response does not match that shape, so a new
endpoint with a different envelope fails the build rather than generating
something misleading.

## Coverage

The gate is 100% lines in five of the seven languages, and it is reached
mechanically rather than by hand. `emit_conformance.py` generates, per language:

- one round trip per model and per enum, reading every field
- one request-mapping test per operation, asserting the method, the resolved
  path, every query key and every body key
- a page walk per paginated operation
- an error-propagation and a nil-params pass

Sample values come from `codegen/samples.py`, which walks the model IR and
synthesizes a deterministic value per type. When the spec grows, the tests grow
with it, so the gate cannot rot at the next sync.

Hand-written tests cover the runtime: transport, retries, paging, errors and
webhook verification.

One exclusion: Go's coverage is scoped to the two packages this repo writes.
`go/internal/openapi` is oapi-codegen's output, and its union helpers carry
eight `if err != nil` branches after a `json.Marshal` of a string, which cannot
fail.

Two languages sit below 100 and hold a floor instead, which only ever rises:

| Language | Floor | Why |
|---|---|---|
| Rust | 89 | `llvm-cov` attributes derive-expanded code to the derive line, so every model needs its `Debug` and `Clone` driven before this reaches 100. `error.rs` and `transport.rs` also have untested branches. |
| Ruby | 83 | No generated conformance suite yet, so the resource methods are never driven. It reaches 100 when `emit_conformance.py` gains a Ruby emitter. |

Neither number is a target. Lower one only when the code genuinely shrank, and
raise it whenever a change earns it.

## Adding or changing an operation

Nothing here needs editing. Refresh `spec/openapi.yaml`, run `make all`, run
`make test`. New operations appear in all eight clients with tests.

Two things in the spec need a workaround table in `codegen/naming.py`:

- `usage_retrieve` is not dotted, and the webhook operations use a singular
  `webhook.` prefix with colliding list and get names, so `OPERATION_RENAMES`
  patches them.
- The envelope always wraps `results` in an array, so cardinality cannot be
  read off the response schema. `FORCE_LIST` and `FORCE_SINGLE` classify the
  operations a `page` query parameter does not settle.

Both would be better fixed in the spec, and both tables shrink when they are.

## Toolchains

Go needs its types from OpenAPI 3.0, and the spec is 3.1, so `downgrade.py`
rewrites a throwaway copy for oapi-codegen only. Everything else reads 3.1.

Reproducibility matters because the `codegen` job diffs the tree:
`datamodel-code-generator`, `oapi-codegen` and `ruff` are pinned, since a
formatting change in any of them would turn the job red on an unrelated day.

PHP and Rust suites run in containers so no local install is needed. C# runs
both target frameworks under one SDK image using `DOTNET_ROLL_FORWARD`.

## Releasing

Each client holds its own version, in the manifest its registry reads, so one
language can release without dragging the other six along.

| Language | Version lives in |
|---|---|
| Python | `python/pyproject.toml` |
| TypeScript | `js/package.json` |
| Rust | `rust/Cargo.toml` |
| Ruby | `ruby/lib/zelf/version.rb` |
| C# | `csharp/src/Zelf.csproj` |
| Java | `java/pom.xml` |
| Go | `go/client.go` |

`codegen/release.py` reads each one back before the emitters rewrite the
manifest, so regenerating never resets a client to someone else's number. The
root `VERSION` file is only the seed for a client that has no manifest yet.

To release one client: edit its version, run `make all`, commit, then publish a
GitHub release whose tag carries that language's prefix (`py/v1.1.0`,
`js/v1.1.0`, `go/v1.1.0`). The publish workflow keys off the prefix, so only
that language goes out.
