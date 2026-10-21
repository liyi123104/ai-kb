# 一键启动：Ollama → 后端 → 前端，全部就绪后自动打开浏览器
# 用法：双击同目录的 start.bat（它会用 Bypass 执行策略调用本脚本）

$ErrorActionPreference = 'SilentlyContinue'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

function Wait-Url($url, $seconds, $name) {
    for ($i = 0; $i -lt $seconds; $i++) {
        try {
            $r = Invoke-WebRequest $url -TimeoutSec 2 -UseBasicParsing
            if ($r.StatusCode -eq 200) { Write-Host "  [OK] $name" -ForegroundColor Green; return $true }
        } catch { }
        Start-Sleep -Seconds 1
    }
    Write-Host "  [FAIL] $name 未就绪（$url）" -ForegroundColor Red
    return $false
}

Write-Host "=== AI 学习资料知识库 启动中 ===" -ForegroundColor Cyan

# 1) Ollama
if (-not (Get-Process -Name 'ollama app' -ErrorAction SilentlyContinue)) {
    $app = Join-Path $env:LOCALAPPDATA 'Programs\Ollama\ollama app.exe'
    if (Test-Path $app) {
        Write-Host "[1/3] 启动 Ollama ..."
        Start-Process -FilePath $app
        Start-Sleep -Seconds 5
    } else {
        Write-Host "[1/3] 找不到 Ollama，请先安装：https://ollama.com/" -ForegroundColor Red
        Read-Host "按回车退出"
        exit 1
    }
} else {
    Write-Host "[1/3] Ollama 已在运行"
}
if (-not (Wait-Url 'http://127.0.0.1:11434/api/version' 30 'Ollama 服务')) {
    Read-Host "Ollama 没起来，按回车退出"
    exit 1
}

# 2) 后端
$backendUp = $false
try {
    $r = Invoke-WebRequest 'http://127.0.0.1:8000/health' -TimeoutSec 2 -UseBasicParsing
    $backendUp = ($r.StatusCode -eq 200)
} catch { }
if (-not $backendUp) {
    Write-Host "[2/3] 启动后端 ..."
    $py = Join-Path $root '.venv\Scripts\python.exe'
    if (-not (Test-Path $py)) {
        Write-Host "找不到 .venv，请先按 README 创建虚拟环境" -ForegroundColor Red
        Read-Host "按回车退出"
        exit 1
    }
    Start-Process -FilePath $py -ArgumentList '-m', 'app.main' -WorkingDirectory $root -WindowStyle Hidden
    if (-not (Wait-Url 'http://127.0.0.1:8000/health' 60 '后端 8000')) {
        Read-Host "后端启动失败，按回车退出"
        exit 1
    }
} else {
    Write-Host "[2/3] 后端已在运行"
}

# 3) 前端
$frontendUp = $false
try {
    $r = Invoke-WebRequest 'http://127.0.0.1:5173' -TimeoutSec 2 -UseBasicParsing
    $frontendUp = ($r.StatusCode -eq 200)
} catch { }
if (-not $frontendUp) {
    if (-not (Test-Path (Join-Path $root 'web\node_modules'))) {
        Write-Host "前端依赖未安装，请先执行：" -ForegroundColor Yellow
        Write-Host "  cd D:\ai-kb\web; npm install --registry=https://registry.npmmirror.com" -ForegroundColor Yellow
        Read-Host "按回车退出"
        exit 1
    }
    Write-Host "[3/3] 启动前端 ..."
    Start-Process -FilePath 'cmd.exe' -ArgumentList '/c', 'cd /d D:\ai-kb\web && npm run dev' -WindowStyle Hidden
    if (-not (Wait-Url 'http://127.0.0.1:5173' 60 '前端 5173')) {
        Read-Host "前端启动失败，按回车退出"
        exit 1
    }
} else {
    Write-Host "[3/3] 前端已在运行"
}

Write-Host ""
Write-Host "=== 全部就绪，正在打开浏览器 ===" -ForegroundColor Green
Write-Host "  前端界面 : http://127.0.0.1:5173"
Write-Host "  后端文档 : http://127.0.0.1:8000/docs"
Start-Process 'http://127.0.0.1:5173'
Start-Sleep -Seconds 2
