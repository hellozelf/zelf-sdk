# --no-project: this directory has no pyproject.toml, so without it uv walks up
# and adopts whatever project it finds above the checkout. Inside the plato
# monorepo that is plato itself, and the generator ends up syncing Django,
# botocore and grpcio before it writes a line.
GEN := uv run --no-project --with pyyaml --with datamodel-code-generator python codegen
LANGS := python js go rust ruby csharp java

.PHONY: all $(LANGS) fixtures test cov e2e \
	$(addprefix test-,$(LANGS)) $(addprefix cov-,$(LANGS)) $(addprefix e2e-,$(LANGS)) clean

all: fixtures
	$(GEN)

$(LANGS):
	$(GEN) $@

fixtures:
	uv run --no-project --with pyyaml python codegen/make_fixtures.py

test: test-python test-js test-go test-rust test-ruby test-csharp test-java

cov: cov-python cov-js cov-go cov-rust cov-ruby cov-csharp cov-java

cov-python:
	cd python && uv run pytest tests -q --cov --cov-report=term-missing

GO_PKGS := github.com/hellozelf/zelf-sdk/go,github.com/hellozelf/zelf-sdk/go/webhooks

cov-go:
	cd go && go test ./... -covermode=atomic -coverpkg=$(GO_PKGS) \
		-coverprofile=cover.out && \
		go tool cover -func=cover.out | awk '/^total:/{print $$3}' | grep -qx '100.0%'

cov-csharp:
	docker run --rm -e DOTNET_ROLL_FORWARD=Major \
		-v "$(CURDIR)/csharp:/csharp" -v "$(CURDIR)/fixtures:/fixtures" \
		-w /csharp/tests mcr.microsoft.com/dotnet/sdk:10.0 dotnet test -v q --nologo \
		/p:CollectCoverage=true /p:SkipAutoProps=true \
		/p:Threshold=100 /p:ThresholdType=line /p:ThresholdStat=total

cov-java:
	cd java && mvn -B verify

cov-rust:
	cd rust && cargo llvm-cov --all-features --fail-under-lines 89 \
		--ignore-filename-regex '(tests|examples)/'

cov-ruby:
	cd ruby && bundle exec ruby -Itest test/all.rb

cov-js:
	cd js && npm run build && node --test --experimental-strip-types \
		--experimental-test-coverage --test-coverage-lines=100 \
		--test-coverage-exclude='test/**' 'test/*.test.ts'

test-python:
	cd python && uv run pytest tests -q

test-js:
	cd js && npm run build && node --test --experimental-strip-types test/*.test.ts

test-go:
	cd go && go test ./...

test-rust:
	docker run --rm -v "$(CURDIR)/rust:/app" -v "$(CURDIR)/fixtures:/fixtures" \
		-w /app rust:slim cargo test

test-ruby:
	cd ruby && for f in test/*_test.rb; do ruby -Itest "$$f" || exit 1; done

test-csharp:
	docker run --rm -e DOTNET_ROLL_FORWARD=Major \
		-v "$(CURDIR)/csharp:/csharp" -v "$(CURDIR)/fixtures:/fixtures" \
		-w /csharp/tests mcr.microsoft.com/dotnet/sdk:10.0 dotnet test -v q --nologo

test-java:
	cd java && mvn -q test

clean:
	rm -rf .tools python/zelf js/src js/dist js/node_modules go/internal \
		rust/src rust/target ruby/lib csharp/src java/src/main

e2e: $(addprefix e2e-,$(LANGS))

e2e-python:
	cd python && uv run pytest e2e -q

e2e-js:
	cd js && npm run build && node --test --experimental-strip-types e2e/*.test.ts

e2e-go:
	cd go && go test -tags e2e ./e2e/...

e2e-rust:
	cd rust && cargo test --test e2e_sandbox -- --ignored

e2e-ruby:
	cd ruby && ruby -Ilib e2e/sandbox_test.rb

e2e-csharp:
	cd csharp/e2e && dotnet test -v q --nologo

e2e-java:
	cd java && mvn -B verify -DskipITs=false

