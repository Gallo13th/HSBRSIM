<#
.SYNOPSIS
    rea_analyze_dotnet.ps1 — 给定 .NET 程序集路径 → 用 REA (rea-agents) 做静态
    托管代码分析 → 输出 JSON（artifact 身份 + 可选类型的 members/call-edges/字符串）。

.DESCRIPTION
    本脚本只做**静态元数据分析**（不加载程序集、不执行任何目标代码），
    对应 REA 的两个子命令：

        rea inspect-managed-artifact  <dll>              # PE/CLI 身份、metadata、references
        rea inspect-managed-members   <dll> --type <T>   # 指定类型的字段/方法/CIL 锚点/ldstr 字符串

    为什么需要它：
      * 本机系统 Node 为 v22.15，REA 要求 node ^22.19 || ^24.11 || >=26，因此脚本
        使用项目内的便携 Node 24（reversed/rea/node/node.exe），**不修改系统 Node**。
      * REA 的 `rea setup` 会写 agent/MCP 配置；本脚本**不做 setup**，只用 CLI 子命令，
        避免污染 DSH/Claude 等配置。

    已知限制（2026-10-18 实测）：
      * Assembly-CSharp.dll (23MB) 的 `inspect-managed-members` 会因内部
        managed-metadata 表示预算（64MiB）超限而失败：
        coverage.state=unavailable, issue.code=resource-limit。
        此时仍可用 `inspect-managed-artifact`；成员级信息请用
        ilspycmd / Mono.Cecil（本项目 reversed/net/ 已有产物）。
      * REA 的托管 provider 不做 C# 反编译（原话："did not ... decompile C#"），
        需要方法体时用 `ilspycmd -t <type>` 作为补充证据。

.PARAMETER DllPath
    程序集路径（只读）。必须存在。

.PARAMETER OutDir
    输出目录。默认 <repo>/reversed/rea/<assembly-name>/。

.PARAMETER Types
    要做成员级分析的类型全名。嵌套类型写作 `Namespace.Outer+Nested`。
    省略 = 只做 artifact 级分析。

.PARAMETER TimeoutSec
    单次 REA 调用超时（秒），默认 300。大程序集 metadata 解析较慢。

.EXAMPLE
    pwsh tools/rea_analyze_dotnet.ps1 `
      -DllPath "%USERPROFILE%\AppData\Local\HearthstoneDeckTracker\app-1.53.0\BobsBuddy.dll" `
      -Types BobsBuddy.Simulation.Simulator,BobsBuddy.Simulation.Minion

.EXAMPLE
    pwsh tools/rea_analyze_dotnet.ps1 -DllPath "C:\Program Files (x86)\Hearthstone\BepInEx\plugins\HsMod.dll"
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$DllPath,

    [string]$OutDir,

    [string[]]$Types = @(),

    [int]$TimeoutSec = 300
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

# ── 0. 定位 repo 根（脚本在 <repo>/tools/ 下） ─────────────────────────
$RepoRoot = Split-Path -Parent $PSScriptRoot
$ReaRoot = Join-Path $RepoRoot 'reversed\rea'
$NodeDir = Join-Path $ReaRoot 'node'
$NodeExe = Join-Path $NodeDir 'node.exe'
$ReaInstall = Join-Path $ReaRoot 'rea-install'
$ReaCmd = Join-Path $ReaInstall 'node_modules\.bin\rea.cmd'

function Fail([string]$msg) {
    Write-Error $msg
    exit 2
}

# ── 1. 校验输入 ───────────────────────────────────────────────────────
if (-not (Test-Path -LiteralPath $DllPath)) { Fail "DLL not found: $DllPath" }
$DllPath = (Resolve-Path -LiteralPath $DllPath).Path
$asmName = [System.IO.Path]::GetFileNameWithoutExtension($DllPath)
if (-not $OutDir) { $OutDir = Join-Path $ReaRoot $asmName }
if (-not (Test-Path -LiteralPath $OutDir)) {
    New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
}
$OutDir = (Resolve-Path -LiteralPath $OutDir).Path

# ── 2. 便携 Node 24（不碰系统 Node） ──────────────────────────────────
if (-not (Test-Path -LiteralPath $NodeExe)) {
    Write-Host "[rea] portable node missing -> downloading Node v24.13.0 into $NodeDir"
    New-Item -ItemType Directory -Force -Path $NodeDir | Out-Null
    $zip = Join-Path $ReaRoot 'node24.zip'
    Invoke-WebRequest -Uri 'https://nodejs.org/dist/v24.13.0/node-v24.13.0-win-x64.zip' `
        -OutFile $zip -UseBasicParsing -TimeoutSec 600
    $tmp = Join-Path $ReaRoot 'node_tmp'
    Expand-Archive -Path $zip -DestinationPath $tmp -Force
    Copy-Item (Join-Path $tmp 'node-v24.13.0-win-x64\*') $NodeDir -Recurse -Force
    Remove-Item $zip -Force
    Remove-Item $tmp -Recurse -Force
}
$nodeVersion = (& $NodeExe --version).Trim()
Write-Host "[rea] node = $nodeVersion ($NodeExe)"

# ── 3. 本地安装 REA（避开 npx 每次解析 + 避开 rea setup） ──────────────
if (-not (Test-Path -LiteralPath $ReaCmd)) {
    Write-Host "[rea] installing rea-agents locally into $ReaInstall"
    New-Item -ItemType Directory -Force -Path $ReaInstall | Out-Null
    Push-Location $ReaInstall
    try {
        $env:PATH = "$NodeDir;$env:PATH"
        $env:npm_config_cache = Join-Path $ReaRoot 'npm-cache'
        & (Join-Path $NodeDir 'npm.cmd') init -y 2>&1 | Out-Null
        & (Join-Path $NodeDir 'npm.cmd') install rea-agents@latest --no-audit --no-fund 2>&1 |
            Select-Object -Last 3 | ForEach-Object { Write-Host "[npm] $_" }
    }
    finally { Pop-Location }
}
if (-not (Test-Path -LiteralPath $ReaCmd)) { Fail "REA install failed; $ReaCmd missing" }

$env:PATH = "$NodeDir;$env:PATH"
$reaVersion = (& $ReaCmd --version 2>&1 | Select-Object -First 1)
Write-Host "[rea] $reaVersion"

$summary = [ordered]@{
    generated_at_utc = (Get-Date).ToUniversalTime().ToString('o')
    tool             = @{ name = 'rea-agents'; version = "$reaVersion"; node = $nodeVersion }
    dll              = $DllPath
    assembly         = $asmName
    output_dir       = $OutDir
    artifact         = $null
    type_analyses    = @()
    notes            = @()
}

function Invoke-Rea {
    param([string[]]$ReaArgs, [string]$OutFile)
    $job = Start-Job -ScriptBlock {
        param($rea, $nodeDir, $argList)
        $env:PATH = "$nodeDir;$env:PATH"
        & $rea @argList 2>&1
    } -ArgumentList $ReaCmd, $NodeDir, $ReaArgs
    if (-not (Wait-Job $job -Timeout $TimeoutSec)) {
        Stop-Job $job; Remove-Job $job -Force
        return @{ ok = $false; exit = -1; text = "timeout after ${TimeoutSec}s" }
    }
    $text = (Receive-Job $job) -join "`n"
    $state = $job.State
    Remove-Job $job -Force
    if ($OutFile) { Set-Content -LiteralPath $OutFile -Value $text -Encoding utf8 }
    return @{ ok = ($state -eq 'Completed'); exit = 0; text = $text }
}

# ── 4. artifact 级分析 ────────────────────────────────────────────────
Write-Host "[rea] inspect-managed-artifact $DllPath"
$artifactFile = Join-Path $OutDir 'rea_artifact.json'
$r = Invoke-Rea -ReaArgs @('inspect-managed-artifact', $DllPath, '--format', 'json') -OutFile $artifactFile
if (-not $r.ok) {
    $summary.notes += "artifact inspection failed: $($r.text)"
    Write-Host "[rea] artifact inspection FAILED: $($r.text)"
}
else {
    try {
        $a = Get-Content -LiteralPath $artifactFile -Raw -Encoding utf8 | ConvertFrom-Json
        $n = $a.normalized_result
        $summary.artifact = [ordered]@{
            sha256       = $n.artifact.sha256
            byte_length  = $n.artifact.byte_length
            format       = $n.artifact.format
            machine      = $n.pe.machine
            architecture = $n.pe.architecture
            metadata     = $n.metadata.status
            assembly     = @{ name = $n.assembly.name; version = $n.assembly.version }
            references   = @($n.references | ForEach-Object { "$($_.name) $($_.version)" })
            coverage     = $n.coverage
            evidence_id  = $a.evidence_id
        }
        Write-Host ("[rea]   sha256={0} refs={1} coverage={2}" -f `
                $n.artifact.sha256.Substring(0, 16), @($n.references).Count, $n.coverage.state)
    }
    catch {
        $summary.notes += "artifact json parse failed: $($_.Exception.Message)"
    }
}

# ── 5. 成员级分析（按类型） ───────────────────────────────────────────
foreach ($t in $Types) {
    $safe = ($t -replace '[^A-Za-z0-9_.]', '_')
    $file = Join-Path $OutDir ("rea_members_{0}.json" -f $safe)
    Write-Host "[rea] inspect-managed-members --type $t"
    $r = Invoke-Rea -ReaArgs @('inspect-managed-members', $DllPath, '--type', $t, '--format', 'json') -OutFile $file
    $entry = [ordered]@{
        type         = $t
        json         = $file
        ok           = $r.ok
        coverage     = $null
        counts       = $null
        methods      = @()
        user_strings = @()
        limitation   = $null
    }
    if (-not $r.ok) {
        $entry.limitation = $r.text
        $summary.type_analyses += [pscustomobject]$entry
        continue
    }
    try {
        $m = Get-Content -LiteralPath $file -Raw -Encoding utf8 | ConvertFrom-Json
        $n = $m.normalized_result
        if ($null -eq $n) {
            $entry.limitation = 'normalized_result is null'
        }
        else {
            $entry.coverage = $n.coverage
            $entry.counts = [ordered]@{
                types          = @($n.types).Count
                fields         = @($n.fields).Count
                methods        = @($n.methods).Count
                member_refs    = @($n.member_refs).Count
                call_edges     = @($n.call_edges).Count
                field_accesses = @($n.field_accesses).Count
            }
            $entry.methods = @($n.methods | ForEach-Object {
                    [ordered]@{
                        name    = $_.name
                        token   = $_.token
                        il_size = $_.body.il_size
                        il_sha  = $_.body.il_sha256
                    }
                })
            $entry.user_strings = @($n.user_strings.literals)
            if (@($n.limitations).Count -gt 0) { $entry.limitation = @($n.limitations) -join ' | ' }
        }
        Write-Host ("[rea]   methods={0} coverage={1}" -f `
                @($n.methods).Count, $n.coverage.state)
    }
    catch {
        $entry.limitation = "json parse failed: $($_.Exception.Message)"
    }
    $summary.type_analyses += [pscustomobject]$entry
}

# ── 6. 汇总 ───────────────────────────────────────────────────────────
$summaryFile = Join-Path $OutDir 'rea_summary.json'
$summary | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $summaryFile -Encoding utf8
Write-Host "[rea] summary -> $summaryFile"
if ($summary.artifact) {
    Write-Host "[rea] OK"
    exit 0
}
Write-Host "[rea] artifact inspection unavailable — see notes"
exit 1
