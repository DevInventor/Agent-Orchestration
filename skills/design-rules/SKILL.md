---
name: design-rules
description: Language-agnostic design rules for production code in any repo - one-way layers, isolated modules, wire types apart from storage, one error family, explicit wiring, one way per cross-cutting concern, size limits, one source of truth, and a test per use case. Generalised from an enforced ArchUnit/PMD rulebook. Use when writing, reviewing or refactoring code, when a review finding cites a rule id such as D7, or when asked to check code against design rules.
---

# Design rules

The house rules for code that any agent or developer writes, in any language. They are
generalised from a Java rulebook (GTID-Vault, ADR-0008) that enforces each of them as a
build check with ArchUnit and PMD. Here they are stated so they hold in any stack. Each
rule has a fix recipe under the same id in [FIXES.md](FIXES.md). [LANGUAGES.md](LANGUAGES.md)
shows each rule's idiom per language and the native tool that can enforce it.

## Which rules win

1. **The repo's own rules come first.** That means its CLAUDE.md or AGENTS.md, its ADRs, its
   architecture tests and its lint config. They are specific and already enforced, so these
   rules only fill the gaps.
2. **Then these rules.**
3. **Then the conventions of the existing code,** where neither of the above says anything.

A rule here asks for *one* way of doing a thing, not for *this* way. If the repo already
does it one way consistently (its own error family, its own layout), follow the repo.

## Writing code

- Read the table once before you start, and apply it as you write.
- **Before you hand off, run the self-check below on your own diff, and fix what it finds
  in the same turn.** A violation fixed then costs nothing. One the reviewer finds costs a
  fix round.
- The rules apply to the code you add or change. Do not refactor untouched code unless you
  were asked to, but do not copy its violations into new code either.

## Reviewing code

- Every design finding names its rule (`"rule": "D7"`), the exact place, and the fix in one
  line. The coder looks the rule up in FIXES.md.
- **Severity follows the rule's level and where the violation is:**
  - A **must** rule broken by this diff is `blocking`.
  - A **should** rule broken by this diff is `major` (`minor` if it is trivial).
  - A violation in code the diff did not touch is at most `minor`: an improvement note,
    never a blocker.
- Taste is not a finding. If it is not in the table, it is not a design finding.

## The rules

| ID | Level | Rule | Spot it in a diff |
|---|---|---|---|
| D1 | must | **One-way layers.** Entry points (HTTP handlers, CLI commands, consumers, jobs) call services, services use the domain, and the domain uses storage, never the reverse. Entry points never touch storage. Services never see transport types. Storage and domain never know the wire format. | a handler importing a repository, ORM or SQL; a service taking an HTTP request; a model importing a DTO |
| D2 | must | **Modules are isolated.** One feature never imports another feature's internals. Shared code lives in a platform module that imports no feature. | an import crossing feature folders; shared or common importing a feature |
| D3 | must | **No dependency cycles** between modules or layers. | A imports B and B imports A, directly or through a third module |
| D4 | should | **One layout, everywhere.** Every feature uses the same small set of folders, and each kind of code lives in its own folder. Only the entry point sits at the root, and there is no nesting the layout does not already have. | a new folder name; a service in the handlers folder; a stray root file |
| D5 | should | **No dumping grounds.** No class, module or folder named Util, Utils, Helper, Manager, Misc, Common or Stuff that holds logic. | a new file or folder with one of those names |
| D6 | should | **Names say what a thing is.** One suffix per kind (Service, Handler/Controller, Repository/Store, Dto, Mapper, Config, Error). Fields are named after what they hold. No delivery labels (v2, new, phase3, sprint or ticket ids) in identifiers, tables or settings. | `UserServiceNew`, `phase2Flag`, `data2`, `x` |
| D7 | must | **Wire types are not storage types.** Persistence models (ORM entities, DB rows) never cross the boundary. Wire DTOs are immutable values, and conversion happens in one mapper at the boundary. | an entity in a handler signature or a response body; a DTO with an entity field; mapping inline in a handler |
| D8 | must | **Validate once, at the boundary.** Every inbound payload is validated declaratively where it enters (schema, annotations, validator), and inner code trusts it. | an unvalidated request body; hand-written field checks inside a service |
| D9 | should | **Thin entry points.** A handler translates the request, calls one service method and translates the result. Its body holds no branching, loops, arithmetic, type checks, try/catch or throws. It depends only on services, mappers and config. | `if`, `for`, `switch` or `try` in a route handler |
| D10 | must | **One error family.** A domain failure is a typed error from one family that carries what the boundary needs (status, code). No bare generic errors, except argument or state guard clauses. | `throw new Error("...")`, `raise Exception(...)`, an untyped error returned from domain code |
| D11 | must | **Errors become responses in one place.** One central handler or middleware maps the error family to responses. Handlers do not build error responses. | `res.status(404).json(...)` or a hand-built error body in a handler |
| D12 | must | **Catch narrowly, never swallow.** Catch only an error you can handle, and handle it (retry, fallback, translate). No catch-all in feature code. Never catch your own error family mid-flight. Never silence an error. | `catch (Exception e)`, `except Exception:`, an empty catch, `except: pass`, an ignored error return |
| D13 | must | **Dependencies come in explicitly.** Collaborators arrive through constructor, factory or function parameters and do not change afterwards. No field or setter injection, no service locator, no module-level singleton reached from inside logic, and no `new` of a collaborator in business code. Building data objects is fine. | `new UserRepository()` in a service; an `@Autowired` field; a global client used inside a function |
| D14 | should | **One way for each cross-cutting concern.** One logger, never print/console/stdout in production code. One time API with an injectable clock, storing UTC and converting timezones in one place. One cache mechanism (no hand-rolled map caches in services). One HTTP client, one config source, one transaction mechanism. | `console.log`, `print(`, `System.out`; `new Date()` or `datetime.now()` in domain logic; a map field used as a cache |
| D15 | must | **The unit of work is the service method.** Transactions and consistency boundaries begin and end in the service layer, never in handlers or storage. | a transaction opened in a handler or a repository |
| D16 | must | **Never kill the process from code that serves requests.** No `exit`, `os.Exit`, `process.exit` or `System.exit` outside startup validation, which may fail fast before serving. | an exit call in a handler, service or library |
| D17 | should | **Small, flat functions.** Cognitive complexity at most 15, cyclomatic at most 15, nesting at most 3 levels, NPath at most 200. Prefer guard clauses and merged conditions. | arrow-shaped code; a function you have to scroll |
| D18 | should | **No god units.** A class or module that is large, incohesive (its methods share few fields) *and* reaches into other objects' data gets split by responsibility. | many unrelated public methods; methods mostly reading another object's getters |
| D19 | should | **No copy-paste.** A block of about 10 or more lines (around 100 tokens) that repeats is extracted once. | the same block twice in the diff, or copied from existing code |
| D20 | must | **One source of truth per fact.** Each fact (a secret, a token, a setting, a route list) is stored or declared in exactly one place. Anything else is derived from it and named as derived. Two lists that must agree are generated from one, or checked against each other by a test. | a second copy of a token, column or constant; a hand-kept list that mirrors the code |
| D21 | must | **Variation is data, not branches.** Core logic never branches on a customer, tenant, vendor or environment name. The difference is expressed as a generic setting or capability. | `if vendor == "slack"`, `if tenant == "acme"` |
| D22 | should | **One shape per kind.** Where the codebase has a standard shape for a kind (a base entity with identity and auditing, a base service, a base handler), new code uses it. A second shape for the same kind is a recorded decision. | an entity without the base; a parallel pattern for something that already exists |
| D23 | must | **Every use case has a test, in its tier.** Each use case the diff changes has a test named after the behaviour and driven through the public interface. Unit and integration tests are kept apart by the repo's convention, and integration tests share its one fixture. Tests are deterministic, with an injected clock and randomness and no sleeps. | new behaviour with no test; `sleep(` in a test; a test named `test1` |

## Self-check before hand-off

Run this pass over your diff, in this order. It takes minutes.

1. **Imports (D1–D3, D13).** Does any new import point up a layer or across features, or
   close a loop? Is any collaborator built or fetched inside logic rather than passed in?
2. **The boundary (D7–D9, D11).** Does an entity or row cross the wire? Is input validated
   where it enters? Does a handler hold logic, or build an error response?
3. **Errors (D10–D12, D16).** Any generic error thrown, any catch-all, any swallowed or
   ignored error, any exit call?
4. **Cross-cutting (D14, D15).** Any print, raw clock, hand-made cache, or transaction
   outside a service?
5. **Shape (D4–D6, D17–D19, D22).** Any new dumping-ground name or delivery label? A
   function past the limits? A duplicated block? A second shape for an existing kind?
6. **Truth (D20, D21).** Did you copy a fact that already has a home? Branch on a name?
7. **Tests (D23).** Does each use case you touched have a behaviour-named, deterministic
   test in the right tier?

## Exceptions are decisions

When a rule is wrong for a case, change it by recording a decision, not by working around
it. Record the decision in the repo's ADR or decision log with four things: the rule, the
scope (which files), why, and who decided. Then reference the record in a comment at the
site. Never weaken a check to make code pass, and never add a silent local exception.
Inside the pipeline, the coder raises a `question` event rather than deciding alone.

These rules hold best as checks that fail the build. LANGUAGES.md names the native tool for
each rule in each language. Do not add tooling unasked; the planner may plan it as a task.
