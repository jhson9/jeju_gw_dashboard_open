# ==============================================================================
#  create_desktop_shortcut.ps1
# ------------------------------------------------------------------------------
#  바탕화면 + 시작 메뉴에 "JeJu 농업용 지하수 관리·분석" 바로가기(.lnk) 생성.
#
#  목적: Edge --app 모드의 taskbar 아이콘이 favicon 다운샘플로 흐려지는 문제
#  우회. Windows 가 .lnk 의 IconLocation 으로 지정된 .ico 의 적합 frame 을
#  taskbar 에 직접 표시. (taskbar 에 .lnk 를 고정하면 더 안정적.)
#
#  사용법:
#    1) PowerShell 우클릭 → "PowerShell 으로 실행" — 이 파일 더블클릭으로는
#       기본 정책상 안 됨. 또는:
#    2) cmd 에서:  powershell -ExecutionPolicy Bypass -File create_desktop_shortcut.ps1
#
#  1회만 실행하면 됩니다. 이후 taskbar 에 .lnk 를 끌어다 고정 권장.
# ==============================================================================

$ErrorActionPreference = "Stop"

# 절대 경로 — 이 .ps1 가 위치한 폴더가 프로젝트 루트
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$BatPath     = Join-Path $ProjectRoot "Run_JejuDashboard.bat"
$IcoPath     = Join-Path $ProjectRoot "jeju_groundwater_dashboard.ico"

if (-not (Test-Path $BatPath)) {
    Write-Error "Run_JejuDashboard.bat not found at: $BatPath"
    exit 1
}
if (-not (Test-Path $IcoPath)) {
    Write-Error "jeju_groundwater_dashboard.ico not found at: $IcoPath"
    exit 1
}

# 바로가기 이름 — taskbar tooltip 및 표시 이름
$ShortcutName = "JeJu 농업용 지하수 관리·분석.lnk"

# 1) 바탕화면
$DesktopPath  = [Environment]::GetFolderPath("Desktop")
$DesktopLnk   = Join-Path $DesktopPath $ShortcutName

# 2) 시작 메뉴 — taskbar 에 고정하려면 시작메뉴 항목에서 우클릭 → "작업 표시줄에 고정" 가능
$StartMenuPath = [Environment]::GetFolderPath("StartMenu")
$StartMenuLnk  = Join-Path $StartMenuPath $ShortcutName

function New-DashboardShortcut {
    param([string]$LinkPath)

    $WScriptShell = New-Object -ComObject WScript.Shell
    $Shortcut = $WScriptShell.CreateShortcut($LinkPath)

    # TargetPath = cmd.exe 직접 (.bat 을 wrapping). PowerShell 의 hidden 옵션
    # 으로 console 창 최소화. cmd.exe /c <bat> 형식으로 호출.
    $Shortcut.TargetPath        = "$env:WINDIR\System32\cmd.exe"
    $Shortcut.Arguments         = "/c `"$BatPath`""
    $Shortcut.WorkingDirectory  = $ProjectRoot
    $Shortcut.IconLocation      = "$IcoPath,0"   # ,0 = 첫 frame — Windows 가 적정 size 자동 선택
    $Shortcut.Description       = "JeJu 농업용 지하수 관리·분석 대시보드"
    $Shortcut.WindowStyle       = 7              # 7 = Minimized — 콘솔 창 최소화로 띄움
    $Shortcut.Save()

    Write-Host "  - Shortcut created: $LinkPath" -ForegroundColor Green
}

Write-Host ""
Write-Host "========================================================" -ForegroundColor Cyan
Write-Host " JeJu Dashboard 바로가기 생성 중..." -ForegroundColor Cyan
Write-Host "========================================================" -ForegroundColor Cyan

New-DashboardShortcut -LinkPath $DesktopLnk
New-DashboardShortcut -LinkPath $StartMenuLnk

Write-Host ""
Write-Host "완료. 다음 단계:" -ForegroundColor Yellow
Write-Host "  1) 바탕화면의 'JeJu 농업용 지하수 관리·분석' 바로가기 더블클릭"
Write-Host "  2) 실행 후 taskbar 의 해당 아이콘을 우클릭 → '작업 표시줄에 고정'"
Write-Host "  3) 다음 실행부터 taskbar 의 고정 아이콘 클릭으로 바로 실행"
Write-Host ""
Write-Host "주의:" -ForegroundColor Yellow
Write-Host "  - taskbar 의 흐림이 .lnk 적용 후에도 남으면 Edge --app 의 favicon"
Write-Host "    이 우선되는 경우. 그 때는 Edge 캐시 정리 또는 PWA 설치 방식 시도."
Write-Host ""
