# Rules per language

The rules are written to hold in any stack. This page lists the usual idiom for each one,
and the native tool that turns it into a check that fails the build, as ArchUnit and PMD
do in GTID-Vault. The repo's own choice always wins: if it already has a logger, an error
family or a linter, use that one. Add a tool only when a task asks for it.

## Idioms

| Rule | Java / Kotlin | TypeScript / Node | Python | Go | C# / .NET |
|---|---|---|---|---|---|
| D7 immutable DTO | `record` / `data class` | `readonly` type, or one inferred from a schema | `@dataclass(frozen=True)` or a pydantic model | value struct, separate from the storage struct | `record` |
| D8 boundary validation | Bean Validation, `@Valid` on the body | zod, valibot or class-validator at the route | pydantic, marshmallow | a validator in the decode step | DataAnnotations, FluentValidation |
| D10 error family | sealed base exception | `class AppError extends Error` with `code`/`status` | `class AppError(Exception)` hierarchy | typed and sentinel errors, `errors.Is`/`As`, wrapped with `%w` | base exception type |
| D11 one mapping place | `@RestControllerAdvice` | error middleware | exception handler (FastAPI, Flask, Django) | one error-to-status function in the HTTP layer | exception-handling middleware |
| D13 explicit wiring | constructor injection, `final` fields | constructor or factory params; the composition root builds the graph | constructor or function params | `NewX(deps)` sets struct fields | constructor injection through the DI container |
| D14 logger | SLF4J | the app's logger (pino, winston) | `logging.getLogger(__name__)` | `log/slog` | `ILogger<T>` |
| D14 clock | `java.time` plus an injected `Clock` | an injected `now()`; store ISO UTC | timezone-aware UTC plus an injected `now` | `time.Time` in UTC plus an injected clock | `TimeProvider`, `DateTimeOffset` |
| D23 test tiers | `*Test` unit, `*IT` integration | `*.test.ts` vs the repo's integration suffix or folder | `tests/unit`, `tests/integration`, or markers | `_test.go` plus an `integration` build tag | separate unit and integration projects |

## Enforcement

| Rules | Java / Kotlin | TypeScript / JS | Python | Go | C# / .NET |
|---|---|---|---|---|---|
| D1–D3 layers, isolation, cycles | ArchUnit (Kotlin: Konsist) | dependency-cruiser; `import/no-cycle`, `no-restricted-imports` | import-linter (layers, independence and forbidden contracts) | depguard; import cycles are already compile errors | NetArchTest, ArchUnitNET |
| D4–D6 layout, naming | ArchUnit naming and package rules | `@typescript-eslint/naming-convention`; dependency-cruiser path rules | ruff `N`; import-linter | revive | NetArchTest |
| D12 broad or swallowed catch | PMD `AvoidCatchingGenericException`, `EmptyCatchBlock` | `no-empty` | ruff `BLE001`, `E722`, `S110` | errcheck, wrapcheck | CA1031 |
| D14 print / console | PMD `SystemPrintln` | `no-console` | ruff `T20` | forbidigo | BannedApiAnalyzers |
| D16 process exit | PMD `DoNotTerminateVM` | `n/no-process-exit` | an architecture test that greps request paths | forbidigo on `os.Exit` | BannedApiAnalyzers |
| D17 complexity, nesting | PMD `CognitiveComplexity`, `CyclomaticComplexity`, `NPathComplexity`, `AvoidDeeplyNestedIfStmts`; detekt | `complexity`, `max-depth`, `sonarjs/cognitive-complexity` | ruff `C901`, `PLR0912`, `PLR0915` | gocognit, gocyclo, nestif | CA1502 |
| D18 god units | PMD `GodClass` | review | ruff `PLR0904` | review | review |
| D19 duplication | PMD CPD (GTID-Vault: 100 tokens) | jscpd | pylint `R0801`, jscpd | dupl | jscpd |
| D20 two lists that must agree | a test comparing both directions, like GTID-Vault's route-table and seam guards | same | same | same | same |

## Making a rule a check

GTID-Vault's arrangement is worth copying when a repo adopts a tool:
1. **Name the rule in the message.** Each failing check carries its rule id in its message
   (`[rule: D17]`), so a red build points at the recipe in FIXES.md.
2. **Start from the code as it is.** Write the check against today's code, and record the
   existing exceptions as decisions. Then it fails only on new violations, and an old repo
   is not blocked on day one.
3. **Never let a rule pass by looking at nothing.** A rule over a set that happens to be
   empty passes while checking nothing, so assert that the set it judges is non-empty.
