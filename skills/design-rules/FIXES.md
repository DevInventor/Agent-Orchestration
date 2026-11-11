# Fixes, by rule

A finding that cites a rule id lands you here. Each recipe is mechanical on purpose: apply
it to the place the finding names, keep the change inside your task's scope, and check the
"done when" line. **Fix the code, never the rule.** If the recipe does not fit the case,
raise a `question` event; do not invent a third way (SKILL.md, "Exceptions are decisions").

## D1 — One-way layers
- Move the upward call down a layer. A handler that queries storage gets a service method
  that does the query, and the handler calls that method.
- A service that needs request data takes plain values or a command object, not the
  request. The handler unpacks the request.
- A domain or storage type that imports a DTO is fixed by moving the conversion into the
  boundary mapper (D7).
- **Done when:** every import points down a layer: entry, then service, then domain, then storage.

## D2 — Modules are isolated
- If two features need the same thing, move it into the platform or shared module. That
  module must not import any feature.
- If one feature genuinely needs another, define a small public interface (a port) owned by
  the consumer and pass the implementation in. That is a design decision: record it.
- **Done when:** no import path crosses from one feature into another's internals.

## D3 — No dependency cycles
- Find the edge that points the wrong way, usually a lower module calling back up.
- Break it with one of three moves: (a) move the shared piece down into a module both can
  import; (b) invert it with an interface the lower module owns and the upper one
  implements; (c) replace the callback with an event or return value.
- **Done when:** the module graph has no loop, which the cycle tool in LANGUAGES.md confirms.

## D4 — One layout, everywhere
- Move the file into the folder its kind belongs in, using the same folder names as the
  sibling features.
- Delete the new nesting level and flatten its files into the existing folders.
- **Done when:** a reader can predict where the file is from what kind of code it is.

## D5 — No dumping grounds
- Give each function in the `Util`/`Helper`/`Manager` file a home:
  - **On the type whose data it works on**, for example `money.format()` rather than
    `MoneyUtils.format(money)`.
  - **In a small module named for the concept** it serves (`slugify`, `pagination`).
- Delete the dumping-ground file once it is empty.
- **Done when:** every name says what the thing *is* or *does*, not that it is miscellaneous.

## D6 — Names say what a thing is
- Rename the type to the suffix its kind uses in this repo, and rename fields after the
  collaborator or value they hold (`userRepository`, `expiresAt`).
- Strip delivery labels (v2, new, phaseN, ticket ids) from names, tables and settings, and
  move that history into a comment or the commit message.
- **Done when:** a reader at a call site can tell the kind and the content without opening
  the declaration.

## D7 — Wire types are not storage types
- Add an immutable DTO for the request or response. Include only the fields the API
  promises.
- Add one mapper at the boundary that converts DTO to domain on the way in and domain to
  DTO on the way out. Delete inline conversions.
- Change the handler to accept and return DTOs only.
- **Done when:** no entity, ORM model or row type appears in a handler signature, a
  response body or a DTO field.

## D8 — Validate once, at the boundary
- Declare the constraints on the inbound DTO or schema (required, format, range, length),
  and turn validation on where the request is decoded.
- Delete the hand-written checks deeper in. A check that is a business rule rather than an
  input shape stays in the domain and throws a typed error (D10).
- **Done when:** a malformed request fails at the edge with a field-level error, and inner
  code holds no shape checks.

## D9 — Thin entry points
- Move each branch, loop, calculation and try/catch out of the handler into the service
  method it calls. Errors propagate to the central handler (D11).
- Leave the handler with three lines: decode or validate, call the service, map the result.
- **Done when:** the handler body has no control flow and depends only on services,
  mappers and config.

## D10 — One error family
- Replace each generic throw with a typed error from the family. If none fits, add one
  member to the family, in the family's location, carrying status and code.
- Keep plain argument and state guards (`IllegalArgument`, `ValueError`) for programming
  errors only.
- **Done when:** every failure a client can see is a member of the family.

## D11 — Errors become responses in one place
- Delete the error-response building from the handler and throw or return the typed error
  instead.
- Map it once, in the central handler or middleware. Add the mapping there if it is new.
- **Done when:** the error-to-response mapping lives in one file.

## D12 — Catch narrowly, never swallow
- Narrow the catch to the specific error you can handle, then handle it: retry, fall back,
  or translate it into a family error with the cause attached.
- If you cannot handle it, delete the catch and let it propagate.
- Replace each empty catch, `pass`, or ignored error return with handling, or with
  propagation plus a log at the one place it is handled.
- **Done when:** every catch names a specific error and does something about it.

## D13 — Dependencies come in explicitly
- Add the collaborator as a constructor, factory or function parameter, store it in a
  read-only field, and delete the `new`, the global lookup or the injected field.
- Make the composition root (main, the DI config, or the app factory) build and pass it.
- **Done when:** the type's parameters list everything it depends on, and tests can pass
  fakes in.

## D14 — One way for each cross-cutting concern
- **print/console:** replace it with the repo's logger, at the right level and with
  structured fields.
- **Raw clock calls in logic:** take a clock or `now` parameter, store UTC, and convert
  timezones only at the edge.
- **Hand-rolled cache:** use the repo's cache mechanism, and scope the key by tenant or user
  where data is per-tenant.
- **A second HTTP client, config reader or transaction API:** switch to the one the repo
  already uses.
- **Done when:** the diff introduces no second mechanism for anything the repo already does.

## D15 — The unit of work is the service method
- Move the transaction boundary to the service method that owns the use case. Handlers and
  repositories run inside it and never open their own.
- **Done when:** every transaction begins and ends in a service method.

## D16 — Never kill the process from code that serves requests
- Replace the exit call with a typed error (D10) and let the central handler answer.
- Process exit belongs only in startup validation, before the server accepts traffic.
- **Done when:** no exit call is reachable from a request or job path.

## D17 — Small, flat functions
- **Invert conditions into guard clauses:** return or throw early, and the main path runs
  unindented.
- **Merge collapsible ifs** (`if a { if b {…} }` becomes `if a && b {…}`).
- **Extract each coherent block** into a well-named function. A comment that explains a
  block is usually that function's name.
- **Replace a long switch over kinds** with a lookup table, or with behaviour on the kinds
  themselves.
- **Done when:** the function is within the limits, which the complexity tool in
  LANGUAGES.md confirms.

## D18 — No god units
- Group the methods by the fields they use. Each group that shares fields is a candidate
  unit; extract it with a name for that responsibility.
- Move logic that mostly reads another object's data onto that object ("feature envy").
- Do it within your task's scope. A wide split is a planned refactor, not a side effect.
- **Done when:** each unit has one reason to change.

## D19 — No copy-paste
- Extract the repeated block once, into the home the code belongs in (not a Util, D5),
  and call it from both places. Parameterise the parts that differ.
- If the copies are only alike by accident and will diverge, say so in the review reply
  instead of merging them.
- **Done when:** each behaviour has one implementation.

## D20 — One source of truth per fact
- Keep the fact in its one home and make the other place read from it, or derive it at
  build time.
- If two lists must agree (routes and docs, a client's paths and a server's contract,
  config keys and their schema), generate one from the other, or add a test that compares
  both ways.
- **Done when:** changing the fact means changing one place.

## D21 — Variation is data, not branches
- Name the capability the branch stands for (`supportsRefreshRotation`, `maxBatchSize`) and
  make it a setting on the vendor, tenant or environment record.
- Replace the name check with a read of that setting. A new vendor then needs data, not code.
- **Done when:** core logic contains no customer, tenant, vendor or environment names.

## D22 — One shape per kind
- Rebase the new type on the codebase's standard shape (base entity, base service, base
  handler) and delete what that shape already provides.
- If the standard shape genuinely does not fit, stop and raise it. A second shape is a
  recorded decision, not a local choice.
- **Done when:** the new type looks like its siblings.

## D23 — Every use case has a test, in its tier
- Add one test per changed use case, named after the behaviour
  (`rejects_an_expired_token`), driven through the public interface rather than private
  helpers.
- Put it in the tier the repo uses for its kind. Integration tests extend the repo's shared
  fixture rather than building their own.
- Replace sleeps with an injected clock, polling with a timeout, or a deterministic fake.
  Seed randomness.
- **Done when:** each use case in the diff has a behaviour-named test that passes alone,
  in any order.
