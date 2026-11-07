# blastr — 一键发布到 GitHub（不需要 git）
#
# 用法：双击 publish.cmd（不是这个 .ps1）
#   - 会弹一个记事本，把 token 粘进去、保存、关掉窗口，脚本自动继续
#   - 也可以提前把 token 写进同目录的 .github_token
#
# token: https://github.com/settings/tokens/new  -> 勾 `repo` -> 7 天过期

$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$tokenPath = Join-Path $root ".github_token"
$logPath = Join-Path $root "publish.log"

function Write-Step($text, $color = "Gray") { Write-Host $text -ForegroundColor $color }

# 让 python 的中文输出不乱码
$env:PYTHONIOENCODING = "utf-8"
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }

Write-Step ""
Write-Step "  blastr -> GitHub" "Cyan"
Write-Step "  ------------------------------------------------"

# ---- python ----------------------------------------------------------------
function Find-Python {
    $found = Get-ChildItem -Path "$env:USERPROFILE\.dsh\dsh-runtimes\*\dependencies\python\python.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($found) { return $found.FullName }
    foreach ($name in @("python", "python3", "py")) {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        if (-not $cmd) { continue }
        try {
            $version = & $cmd.Source --version 2>&1
            if ($LASTEXITCODE -eq 0 -and $version -match "3\.(9|1[0-9])") { return $cmd.Source }
        } catch { }
    }
    return $null
}

$python = Find-Python
if (-not $python) {
    Write-Step "  找不到 Python 3.9+，先装: winget install Python.Python.3.12" "Red"
    Start-Sleep -Seconds 8
    exit 1
}
Write-Step "  python: $python"

# ---- token -----------------------------------------------------------------
$token = $env:GITHUB_TOKEN
if (-not $token -and (Test-Path $tokenPath)) {
    $token = (Get-Content $tokenPath -Raw -ErrorAction SilentlyContinue)
    if ($token) { $token = $token.Trim() }
}

if (-not $token) {
    Write-Step ""
    Write-Step "  需要一次 token（用完就删，不留盘）" "Yellow"
    Write-Step "  https://github.com/settings/tokens/new  ->  勾 repo"
    Write-Step ""
    Write-Step "  会打开一个记事本：把 token 粘进去 -> Ctrl+S 保存 -> 关掉窗口"
    Start-Sleep -Seconds 2
    if (-not (Test-Path $tokenPath)) { New-Item -ItemType File -Path $tokenPath -Force | Out-Null }
    Start-Process notepad.exe -ArgumentList "`"$tokenPath`""
    Write-Step ""
    Write-Step "  等待保存…（最多等 3 分钟）"

    $deadline = (Get-Date).AddMinutes(3)
    while ((Get-Date) -lt $deadline) {
        if (Test-Path $tokenPath) {
            $candidate = (Get-Content $tokenPath -Raw -ErrorAction SilentlyContinue)
            if ($candidate) { $candidate = $candidate.Trim() }
            if ($candidate) { $token = $candidate; break }
        }
        Start-Sleep -Milliseconds 800
    }
}

if (-not $token) {
    Write-Step "  没有拿到 token，退出。可以把 token 写进 .github_token 再重跑。" "Red"
    Start-Sleep -Seconds 8
    exit 1
}

$env:GITHUB_TOKEN = $token

# ---- run -------------------------------------------------------------------
Write-Step ""
Write-Step "  正在发布，通常 10-30 秒…" "Cyan"
Write-Step ""

try {
    & $python (Join-Path $root "tools\publish_github.py") --repo blastr --public --release 2>&1 |
        Tee-Object -FilePath $logPath
    $code = $LASTEXITCODE
} catch {
    $code = 1
    $_ | Out-File -FilePath $logPath -Append
} finally {
    Remove-Item Env:\GITHUB_TOKEN -ErrorAction SilentlyContinue
}

if ($code -eq 0) {
    Remove-Item $tokenPath -Force -ErrorAction SilentlyContinue
}

Write-Step ""
if ($code -eq 0) {
    Write-Step "  完成，token 文件已删除。" "Green"
    Write-Step "  记得去 https://github.com/settings/tokens 把 token 也 revoke 掉。" "Green"
} else {
    Write-Step "  失败（退出码 $code），细节看同目录的 publish.log。" "Red"
    Write-Step "  常见原因：token 没勾 repo / 已经过期 / 复制时带进了空格。" "Yellow"
}
Write-Step ""
Start-Sleep -Seconds 4
exit $code
