$ErrorActionPreference = "Stop"
$rootDir = (Get-Item -Path $PSScriptRoot).Parent.FullName
$env:TIKTOKEN_CACHE_DIR = Join-Path $rootDir "resources\tiktoken"
Write-Host "[dev.ps1] TIKTOKEN_CACHE_DIR=$env:TIKTOKEN_CACHE_DIR"
Set-Location $rootDir
npm run dev
