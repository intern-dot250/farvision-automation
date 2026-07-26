# Vercel env sync: removes existing prod vars and re-adds from backend/.env
# Usage: .\scripts\vercel-sync-env.ps1

$envFile = "$PSScriptRoot\..\backend\.env"
if (-not (Test-Path $envFile)) {
    Write-Error "Backend .env not found at $envFile"
    exit 1
}

# Parse KEY=VALUE lines, skip blanks and comments
$vars = Get-Content $envFile |
    Where-Object { $_ -match '^\s*([A-Z_][A-Z0-9_]*)\s*=\s*(.+)\s*$' } |
    ForEach-Object {
        $key = $matches[1]
        $val = $matches[2].Trim()
        # Strip surrounding quotes if present
        if ($val -match '^"(.*)"$') { $val = $matches[1] }
        [PSCustomObject]@{ Key = $key; Value = $val }
    }

foreach ($v in $vars) {
    Write-Host "Syncing $($v.Key)..."
    # Remove existing (ignore if not present)
    vercel env rm $env:v.Key production --yes 2>$null | Out-Null
    # Add fresh, non-sensitive
    $env:VERCEL_VALUE = $v.Value
    "n" | vercel env add $v.Key production 2>&1 | Out-Null
    Remove-Item Env:\VERCEL_VALUE -ErrorAction SilentlyContinue
}

Write-Host "Done. Variables synced:"
$vars | ForEach-Object { Write-Host "  - $($_.Key)" }
