# Design decisions

A running log of decisions made **during** implementation. Architectural decisions that
shape the system as a whole live in [`hld.md` §6](hld.md#6-architectural-decisions) as
ADR-01 through ADR-07; this file records the smaller calls made while building, so the
reasoning survives after the diff stops being readable.

Format: what was decided, what else was considered, and why.

---

## DD-01 — Python packages nested inside the mandated hyphenated folders

**Decided.** Keep the mandated directory names exactly (`mcp-servers/alarm-management/`)
and place a correctly-named Python package inside each (`alarm_mcp/`), mapped to a
top-level import through hatchling's multi-root `packages` list.

**Also considered.** Renaming the folders to `mcp_servers/alarm_management/`, which
would be idiomatic Python but would deviate from the structure the guidelines mandate;
or a `PYTHONPATH` shim, which breaks differently in Docker than it does locally.

**Why.** The submission is graded partly on matching the required structure. Deviating
on folder names to satisfy a language constraint would be trading a graded requirement
for a cosmetic one. The mapping is declared once in `pyproject.toml` and is invisible
thereafter — all seven packages import normally.

---

## DD-02 — Dependencies split into optional groups

**Decided.** `simulator`, `mcp`, `backend`, `rag`, `dev`, and an `all` aggregate, rather
than one flat dependency list.

**Why.** Each container installs only what it needs. The RAG group alone pulls
`sentence-transformers` and its ML stack; forcing that into the simulator image would
multiply build time for no benefit. It also makes the dependency footprint of each
component legible from `pyproject.toml` alone.

---

## DD-03 — `tasks.ps1` alongside the Makefile

**Decided.** Keep the Makefile as canonical (CI and containers use it) and add a
PowerShell script exposing the same target names.

**Also considered.** Makefile only, and telling Windows users to install `make`; or
replacing the Makefile with scripts, which would deviate from the mandated structure.

**Why.** `make` is not present on a default Windows install, and the guidelines list a
`Makefile` in the required tree. Both exist, target names match exactly, so a command
that works locally works in CI.

---

## DD-04 — Repo-hygiene test as the first test written

**Decided.** Before any feature code, a test that fails if anything shaped like a live
Anthropic or GitHub credential appears anywhere in the tree, and that asserts
`.env.example` uses placeholder values.

**Why.** "Secrets committed" is listed as an automatic red flag. A test that runs on
every push is a stronger control than remembering to check, and it costs almost nothing.

---

## DD-05 — `.gitattributes` normalising line endings

**Decided.** Force LF for shell scripts, Dockerfiles, Makefiles, and YAML; CRLF for
PowerShell.

**Why.** The repository is authored on Windows and executed in Linux containers. A shell
script committed with CRLF fails inside a container with a misleading
`\r: command not found`. Fixing this at commit time avoids a class of bug that is
painful to diagnose from a build log.

---

## DD-06 — The tool catalog is generated from live servers, not written

**Decided.** `scripts/gen_tool_catalog.py` connects to both MCP servers, calls
`list_tools()`, and captures **real** example responses by invoking each tool against the
seeded simulator. CI runs it with `--check`.

**Also considered.** Writing the catalog by hand in `lld.md` §3 and generating from
Pydantic models — the original plan.

**Why.** A hand-written tool contract and a running server drift the first time a
parameter changes, and a reader cannot tell which one is lying. Generating from
`list_tools()` means the catalog documents the same thing the planner sees. `--check`
normalises timestamps and generated ids before comparing, so the gate fires on schema
drift and not on the clock.

---

## DD-07 — Chroma embedded, and a hashing embedder by default

**Decided.** Chroma runs in-process inside the backend; the default embedder is a
deterministic BLAKE2b feature hash rather than sentence-transformers.

**Also considered.** A `chroma` container (the original six-service topology), and baking
sentence-transformer weights into the image.

**Why.** Both alternatives optimise the wrong thing. A separate vector container adds a
service, a healthcheck, a network hop, and a startup race to a demo of a 49-chunk corpus.
Baked-in model weights add gigabytes and a download to a clean clone. An evaluator's
first `docker compose up` succeeding matters more than marginal recall — and BM25 covers
the exact-term queries that dominate operator questions. Both choices are one environment
variable away from being reversed.

---

## DD-08 — Approval is carried into the tool call, not just past the gate

**Decided.** When a write tool is approved, the executor injects the tool's confirmation
argument (`WRITE_TOOLS = {"create_issue": "confirmed"}`) into the call.

**Why.** This was a real bug, caught by `test_a_confirmed_write_proceeds`: the
orchestrator let the approved step through but never told the server, so the MCP server
refused and an approved write silently failed. Keeping the gate in both places is correct
— but only if the approval actually crosses the boundary.

---

## DD-09 — One container image for four Python services

**Decided.** The simulator, both MCP servers, and the backend share one image and differ
only by command.

**Also considered.** Four Dockerfiles, one per service, each installing only its extra.

**Why.** The extras that differ are a few megabytes of pure Python, while four images
mean four dependency layers to build and cache and four places the Python version can
drift. The trade is stated in known-limitations rather than hidden.

---

## DD-10 — mypy checks shipped code; tests are excluded

**Decided.** `mypy` runs over every package with `disallow_untyped_defs`, and excludes
`tests/`.

**Also considered.** Type-checking tests too (≈31 errors, all from decoded JSON typed as
`dict[str, object]`), or disabling the relevant error codes globally.

**Why.** Annotating every JSON access in the tests would add noise to the most-read files
in the repository in order to re-check what the assertion on the next line already checks
at runtime. Disabling the error codes globally would weaken checking where it matters.
Excluding tests keeps the gate strict on shipped code — and mypy is a hard CI gate
because of it, not an advisory one.
