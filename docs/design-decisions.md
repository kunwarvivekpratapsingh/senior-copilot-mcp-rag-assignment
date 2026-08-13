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
