# 一键停止：关掉后端与前端（Ollama 保持运行，方便下次秒开）
# 用法：双击同目录的 stop.bat

$ErrorActionPreference = 'SilentlyContinue'

Write-Host "=== 停止服务 ===" -ForegroundColor Cyan
foreach ($port in 8000, 5173) {
    $conns = Get-NetTCPConnection -LocalPort $port -State Listen
    if (-not $conns) {
        Write-Host "  端口 $port 本来就没在跑"
        continue
    }
    foreach ($c in $conns) {
        $p = Get-Process -Id $c.OwningProcess
        Write-Host "  停止 $($p.ProcessName) (pid=$($p.Id)) 端口 $port"
        Stop-Process -Id $p.Id -Force
    }
}
Write-Host "=== 已停止（Ollama 仍在后台，重启项目会更快）===" -ForegroundColor Green
Start-Sleep -Seconds 2
