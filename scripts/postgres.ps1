param(
    [ValidateSet("init", "start", "status", "stop")]
    [string]$Action = "status"
)

$ErrorActionPreference = "Stop"

& uv run newsradar db $Action
exit $LASTEXITCODE
