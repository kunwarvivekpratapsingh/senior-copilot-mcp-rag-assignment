<#
.SYNOPSIS
    Windows task runner. Mirrors the Makefile target-for-target.

.DESCRIPTION
    The Makefile is canonical and is what CI and the containers use, but `make`
    is not installed by default on Windows. This script exposes the same target
    names so local development matches CI exactly.

.EXAMPLE
    .\tasks.ps1 install
    .\tasks.ps1 lint
    .\tasks.ps1 test
#>
param(
    [Parameter(Position = 0)]
    [string]$Target = "help"
)

$ErrorActionPreference = "Stop"
$PY = "python"

function Invoke-Step {
    param([string]$Description, [scriptblock]$Action)
    Write-Host "==> $Description" -ForegroundColor Cyan
    & $Action
    if ($LASTEXITCODE -ne 0) { throw "$Description failed (exit $LASTEXITCODE)" }
}

switch ($Target) {
    "help" {
        Write-Host "Targets (mirrors the Makefile):" -ForegroundColor Cyan
        @(
            @{ n = "install";          d = "Install all components plus dev tooling, editable" },
            @{ n = "lint";             d = "Ruff check (includes security rules)" },
            @{ n = "format";           d = "Ruff format in place" },
            @{ n = "typecheck";        d = "mypy static analysis" },
            @{ n = "test";             d = "The whole suite; no running services required" },
            @{ n = "test-unit";        d = "Unit tests only" },
            @{ n = "test-integration"; d = "Integration tests" },
            @{ n = "test-e2e";         d = "Acceptance scenario over the HTTP surface" },
            @{ n = "coverage";         d = "Test suite with coverage report" },
            @{ n = "contract";         d = "Postman collections vs a running simulator" },
            @{ n = "ingest";           d = "Build the RAG index from rag/documents" },
            @{ n = "smoke";            d = "Chain two MCP tools without GUI or LLM" },
            @{ n = "up";               d = "Build and start the full stack" },
            @{ n = "down";             d = "Stop the stack and remove volumes" },
            @{ n = "logs";             d = "Tail logs from every service" },
            @{ n = "ps";               d = "Show service health" },
            @{ n = "docs";             d = "Regenerate tool catalog and diagrams" },
            @{ n = "clean";            d = "Remove caches and build artefacts" }
        ) | ForEach-Object { "  {0,-18} {1}" -f $_.n, $_.d }
    }

    "install"          { Invoke-Step "Installing packages"   { & $PY -m pip install -e ".[all]" } }
    "lint"             { Invoke-Step "Ruff check"            { & $PY -m ruff check . } }
    "format"           { Invoke-Step "Ruff format"           { & $PY -m ruff format . } }
    "typecheck"        { Invoke-Step "mypy"                  { & $PY -m mypy . } }
    "test"             { Invoke-Step "pytest"                { & $PY -m pytest } }
    "test-unit"        { Invoke-Step "pytest unit"           { & $PY -m pytest tests/unit } }
    "test-integration" { Invoke-Step "pytest integration"    { & $PY -m pytest tests/integration } }
    "test-e2e"         { Invoke-Step "pytest e2e"            { & $PY -m pytest tests/e2e } }
    "coverage"         { Invoke-Step "pytest + coverage"     { & $PY -m pytest --cov --cov-report=term-missing --cov-report=html } }
    "ingest"           { Invoke-Step "Building RAG index"    { & $PY -m rag.ingestion.cli --docs ./rag/documents --reset } }
    "smoke"            { Invoke-Step "MCP smoke test"        { & $PY scripts/mcp_smoke.py } }
    "up"               { Invoke-Step "docker compose up"     { docker compose up --build -d } }
    "down"             { Invoke-Step "docker compose down"   { docker compose down -v } }
    "logs"             { Invoke-Step "docker compose logs"   { docker compose logs -f } }
    "ps"               { Invoke-Step "docker compose ps"     { docker compose ps } }

    "contract" {
        Invoke-Step "Postman: baseline" { newman run postman/Alarm-API-Simulator.postman_collection.json }
        Invoke-Step "Postman: scenarios" { newman run postman/scenarios/Alarm-API-Scenarios.postman_collection.json }
        Invoke-Step "Postman: chaining" { newman run postman/chaining/Alarm-API-Chaining.postman_collection.json }
    }

    "docs" {
        Invoke-Step "Generating tool catalog" { & $PY scripts/gen_tool_catalog.py }
        Invoke-Step "Exporting diagrams"      { bash scripts/gen_diagrams.sh }
    }

    "clean" {
        Write-Host "==> Cleaning caches" -ForegroundColor Cyan
        @(".pytest_cache", ".mypy_cache", ".ruff_cache", "htmlcov", "dist", "build") |
            ForEach-Object { if (Test-Path $_) { Remove-Item -Recurse -Force $_ } }
        @(".coverage", "coverage.xml") |
            ForEach-Object { if (Test-Path $_) { Remove-Item -Force $_ } }
        Get-ChildItem -Recurse -Directory -Filter __pycache__ -ErrorAction SilentlyContinue |
            Remove-Item -Recurse -Force
    }

    default {
        Write-Host "Unknown target: $Target" -ForegroundColor Red
        Write-Host "Run '.\tasks.ps1 help' to list targets."
        exit 1
    }
}
