"""Windows desktop alerts through the native notification APIs."""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import subprocess
import sys


_TOAST_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
if (-not [Environment]::UserInteractive -or [Diagnostics.Process]::GetCurrentProcess().SessionId -eq 0) {
    exit 2
}
$message = [Console]::In.ReadToEnd() | ConvertFrom-Json

function Send-Toast {
    $identity = Get-StartApps | Where-Object {
        $_.AppID -like '*\WindowsPowerShell\v1.0\powershell.exe'
    } | Select-Object -First 1 -ExpandProperty AppID
    if (-not $identity) { return 1 }
    $null = [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime]
    $null = [Windows.UI.Notifications.ToastNotification, Windows.UI.Notifications, ContentType = WindowsRuntime]
    $notifier = [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($identity)
    if ($null -eq $notifier) { return 1 }
    $setting = $notifier.Setting
    if ($null -ne $setting -and $setting.ToString() -ne 'Enabled') { return 2 }

    $xml = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent(
        [Windows.UI.Notifications.ToastTemplateType]::ToastText02
    )
    $textNodes = $xml.GetElementsByTagName('text')
    $null = $textNodes.Item(0).AppendChild($xml.CreateTextNode([string]$message.title))
    $null = $textNodes.Item(1).AppendChild($xml.CreateTextNode([string]$message.body))
    $toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
    $notifier.Show($toast)
    return 0
}

try {
    $status = Send-Toast
    if ($status -eq 0 -or $status -eq 2) { exit $status }
} catch {
    # A Start-menu identity can exist without allowing this process to
    # submit toast notifications on its behalf. Use a separate native icon.
}

$icon = $null
try {
    Add-Type -AssemblyName System.Windows.Forms
    Add-Type -AssemblyName System.Drawing
    $icon = [System.Windows.Forms.NotifyIcon]::new()
    $icon.Icon = [System.Drawing.SystemIcons]::Information
    $icon.Text = 'SmartPLAY'
    $icon.Visible = $true
    $title = [string]$message.title
    $body = [string]$message.body
    $title = $title.Substring(0, [Math]::Min(63, $title.Length))
    $body = $body.Substring(0, [Math]::Min(255, $body.Length))
    $icon.ShowBalloonTip(5000, $title, $body, [System.Windows.Forms.ToolTipIcon]::Info)
    $timer = [Diagnostics.Stopwatch]::StartNew()
    while ($timer.ElapsedMilliseconds -lt 6000) {
        [System.Windows.Forms.Application]::DoEvents()
        Start-Sleep -Milliseconds 100
    }
    exit 0
} catch {
    exit 1
} finally {
    if ($null -ne $icon) {
        $icon.Visible = $false
        $icon.Dispose()
    }
}
"""


def _powershell_executable() -> Path | None:
    if sys.platform != "win32":
        return None
    system_root = os.environ.get("SystemRoot", r"C:\Windows")
    candidate = Path(system_root) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    try:
        return candidate if candidate.is_file() else None
    except OSError:
        return None


def desktop_channel() -> str:
    """Return the expected native channel for this OS, or browser fallback."""
    return "windows" if _powershell_executable() is not None else "browser"


def notify_desktop(title: str, body: str) -> bool:
    """Submit a Windows alert and report whether the API call succeeded.

    Call from a background thread. System settings, Do Not Disturb, and an
    inactive user desktop may affect whether Windows shows the banner.
    """
    executable = _powershell_executable()
    if executable is None:
        return False
    message = json.dumps({"title": str(title)[:120], "body": str(body)[:400]}, ensure_ascii=True)
    command = base64.b64encode(_TOAST_SCRIPT.encode("utf-16le")).decode("ascii")
    try:
        result = subprocess.run(
            [str(executable), "-NoLogo", "-NoProfile", "-NonInteractive", "-STA", "-EncodedCommand", command],
            input=message.encode("ascii"),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0
