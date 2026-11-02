# Podcast Watch: a small control window for the folder-watch scheduled task
# (see README.md, "Scheduled / drop folder mode"). Meant to be launched from
# a desktop shortcut with a hidden console, not run interactively.
#
# What it does:
#   - sets up the PodcastGeneratorWatch scheduled task if it doesn't exist
#     (current user, no admin rights, pythonw.exe so no console flashes up)
#   - turns that task on/off and changes how often it runs
#   - optionally forces it on or off whenever the window opens
#     (PODCAST_WATCH_ON_OPEN in .env: on | off; unset = leave it as it was)
#   - picks the inputs/outputs/archive folders, saved to this repo's .env.
#     A folder left at its default (the repo's own inputs/, outputs/,
#     script_archive/) is removed from .env rather than written to it.
#
# Only the keys it changes are rewritten; other .env lines and comments are kept.

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[System.Windows.Forms.Application]::EnableVisualStyles()

$TaskName = "PodcastGeneratorWatch"
$RepoDir  = Split-Path -Parent $PSScriptRoot
$EnvPath  = Join-Path $RepoDir ".env"
$OnOpenKey = "PODCAST_WATCH_ON_OPEN"

$Author = "Brien Alkire"

function Get-AppVersion {
    $path = Join-Path $RepoDir "VERSION"
    try { return (Get-Content -LiteralPath $path -TotalCount 1 -ErrorAction Stop).Trim() } catch { return "unknown" }
}

function Show-About {
    [System.Windows.Forms.MessageBox]::Show(
        "Podcast Watch (podcast_generator)`n`nVersion $(Get-AppVersion)`nAuthor: $Author",
        "About Podcast Watch",
        [System.Windows.Forms.MessageBoxButtons]::OK,
        [System.Windows.Forms.MessageBoxIcon]::Information) | Out-Null
}

function Show-Error([string]$message) {
    [System.Windows.Forms.MessageBox]::Show($message, "Podcast Watch",
        [System.Windows.Forms.MessageBoxButtons]::OK,
        [System.Windows.Forms.MessageBoxIcon]::Error) | Out-Null
}

# ---------------------------------------------------------------- .env I/O

function Read-EnvLines {
    if (Test-Path -LiteralPath $EnvPath) {
        return @(Get-Content -LiteralPath $EnvPath -Encoding UTF8)
    }
    return @()
}

function Get-KeyPattern([string]$key) {
    return "^\s*(?:export\s+)?$([regex]::Escape($key))\s*=\s*(.*)$"
}

function Get-EnvValue([string]$key) {
    $pattern = Get-KeyPattern $key
    foreach ($line in Read-EnvLines) {
        if ($line -match $pattern) {
            $v = $Matches[1].Trim()
            if ($v -match "^'(.*)'$" -or $v -match '^"(.*)"$') {
                $v = $Matches[1]
            } elseif ($v -match '^(.*?)\s+#') {
                $v = $Matches[1]
            }
            if ($v) { return $v }
            return $null
        }
    }
    return $null
}

function Format-EnvValue([string]$value) {
    # Unquoted is fine for Windows paths. Single quotes (no escape
    # processing in python-dotenv) only when a " #" would start a comment.
    if ($value -match '\s#' -and $value -notmatch "'") { return "'$value'" }
    return $value
}

# Sets $key in .env, or removes it when $value is $null.
function Set-EnvValue([string]$key, $value) {
    $pattern = Get-KeyPattern $key
    $lines = New-Object System.Collections.Generic.List[string]
    $isNew = -not (Test-Path -LiteralPath $EnvPath)
    $replaced = $false
    foreach ($line in Read-EnvLines) {
        if ($line -match $pattern) {
            if ($null -ne $value -and -not $replaced) {
                $lines.Add("$key=$(Format-EnvValue $value)")
                $replaced = $true
            }
            continue   # drop the old line (and any duplicates)
        }
        $lines.Add($line)
    }
    if ($null -ne $value -and -not $replaced) {
        if ($isNew) {
            $lines.Add("# Local config for podcast_generator (see .env.example). Not committed.")
            $lines.Add("")
        }
        $lines.Add("$key=$(Format-EnvValue $value)")
    }
    if ($isNew -and $null -eq $value) { return }
    [System.IO.File]::WriteAllLines($EnvPath, $lines, (New-Object System.Text.UTF8Encoding $false))
}

# ------------------------------------------------------ scheduled task

function Get-WatchTask {
    try { return Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop } catch { return $null }
}

function Test-WatchOn($task) {
    return ($null -ne $task -and [string]$task.State -ne "Disabled")
}

function Set-Watch([bool]$on) {
    try {
        if ($on) { Enable-ScheduledTask -TaskName $TaskName -ErrorAction Stop | Out-Null }
        else     { Disable-ScheduledTask -TaskName $TaskName -ErrorAction Stop | Out-Null }
    } catch {
        Show-Error "Could not turn the podcast watch $(if ($on) {'on'} else {'off'}):`n`n$($_.Exception.Message)"
    }
}

function Get-WatchIntervalMinutes($task) {
    try {
        $iv = $task.Triggers | ForEach-Object { $_.Repetition.Interval } |
            Where-Object { $_ } | Select-Object -First 1
        if ($iv) { return [int][System.Xml.XmlConvert]::ToTimeSpan($iv).TotalMinutes }
    } catch {}
    return $null
}

$IntervalChoices = @(5, 10, 15, 30, 60)

function New-WatchTrigger([int]$minutes) {
    return New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
        -RepetitionInterval (New-TimeSpan -Minutes $minutes) `
        -RepetitionDuration (New-TimeSpan -Days 3650)
}

# Registers the watch task for the current user: no admin rights or stored
# password needed, runs only while you're logged in. pythonw.exe means no
# console window flashes up on each check (output goes to generator.log).
function Register-Watch([int]$minutes) {
    $pythonw = Join-Path $RepoDir ".venv\Scripts\pythonw.exe"
    if (-not (Test-Path -LiteralPath $pythonw)) {
        Show-Error ("Couldn't find this repo's Python environment:`n$pythonw`n`n" +
            "Install podcast_generator first (README.md, Installation), then try again.")
        return
    }
    try {
        $action = New-ScheduledTaskAction -Execute $pythonw -Argument "generator.py" -WorkingDirectory $RepoDir
        $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries `
            -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew `
            -ExecutionTimeLimit (New-TimeSpan -Hours 12)
        Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger (New-WatchTrigger $minutes) `
            -Settings $settings -Description "podcast_generator: converts scripts dropped in the inputs folder." `
            -ErrorAction Stop | Out-Null
    } catch {
        Show-Error "Could not set up the podcast watch:`n`n$($_.Exception.Message)"
    }
}

function Set-WatchInterval([int]$minutes) {
    try {
        Set-ScheduledTask -TaskName $TaskName -Trigger (New-WatchTrigger $minutes) -ErrorAction Stop | Out-Null
    } catch {
        Show-Error "Could not change how often the watch checks:`n`n$($_.Exception.Message)"
    }
}

# ------------------------------------------------------------------- UI

function New-Control([string]$type, [int]$x, [int]$y, [int]$w, [int]$h, [string]$text = "") {
    $c = New-Object "System.Windows.Forms.$type"
    $c.Location = New-Object System.Drawing.Point($x, $y)
    $c.Size = New-Object System.Drawing.Size($w, $h)
    if ($text) { $c.Text = $text }
    return $c
}

function Update-WatchUI {
    $task = Get-WatchTask
    if ($null -eq $task) {
        $lblStatus.Text = "Watch not set up"
        $lblStatus.ForeColor = [System.Drawing.Color]::DimGray
        $lblDetail.Text = "Set up a Windows scheduled task that converts dropped scripts automatically."
        $btnToggle.Text = "Set up watch"
        return
    }
    if (Test-WatchOn $task) {
        $lblStatus.Text = "Watch is ON"
        $lblStatus.ForeColor = [System.Drawing.Color]::ForestGreen
        $btnToggle.Text = "Turn OFF"
        $mins = Get-WatchIntervalMinutes $task
        $lblDetail.Text = if ($mins) {
            "Scripts dropped in the inputs folder are converted (checked every $mins minutes)."
        } else {
            "Scripts dropped in the inputs folder are converted automatically."
        }
    } else {
        $lblStatus.Text = "Watch is OFF"
        $lblStatus.ForeColor = [System.Drawing.Color]::Firebrick
        $btnToggle.Text = "Turn ON"
        $lblDetail.Text = "Dropped scripts wait in the inputs folder until watch is turned on."
    }
}

function Update-FolderRow($row) {
    $v = Get-EnvValue $row.Key
    if ($v) {
        $row.Box.Text = $v
        $row.Caption.Text = $row.Label
        $row.Reset.Enabled = $true
    } else {
        $row.Box.Text = $row.Default
        $row.Caption.Text = "$($row.Label)  (default: in this repo)"
        $row.Reset.Enabled = $false
    }
}

function Test-SamePath([string]$a, [string]$b) {
    return $a.TrimEnd('\', '/') -ieq $b.TrimEnd('\', '/')
}

try {
    # Apply the "when this app opens" setting before showing anything.
    $onOpen = (Get-EnvValue $OnOpenKey)
    if ($onOpen) { $onOpen = $onOpen.ToLowerInvariant() }
    $task = Get-WatchTask
    if ($task) {
        if ($onOpen -eq "on" -and -not (Test-WatchOn $task)) { Set-Watch $true }
        elseif ($onOpen -eq "off" -and (Test-WatchOn $task)) { Set-Watch $false }
    }

    $form = New-Object System.Windows.Forms.Form
    $form.Text = "Podcast Watch"
    $form.Font = New-Object System.Drawing.Font("Segoe UI", 9)
    $form.ClientSize = New-Object System.Drawing.Size(640, 404)
    $form.FormBorderStyle = "FixedDialog"
    $form.MaximizeBox = $false
    $form.StartPosition = "CenterScreen"
    try { $form.Icon = [System.Drawing.Icon]::ExtractAssociatedIcon((Get-Command powershell.exe).Source) } catch {}

    # --- Watch group
    $grpWatch = New-Control GroupBox 12 10 616 124 "Folder watch"
    $form.Controls.Add($grpWatch)

    $lblStatus = New-Control Label 16 26 400 30
    $lblStatus.Font = New-Object System.Drawing.Font("Segoe UI", 13, [System.Drawing.FontStyle]::Bold)
    $grpWatch.Controls.Add($lblStatus)

    $btnToggle = New-Control Button 470 24 130 34
    $btnToggle.Add_Click({
        $t = Get-WatchTask
        if ($null -eq $t) { Register-Watch $IntervalChoices[$cmbInterval.SelectedIndex] }
        else { Set-Watch (-not (Test-WatchOn $t)) }
        Update-WatchUI
    })
    $grpWatch.Controls.Add($btnToggle)

    $lblDetail = New-Control Label 18 60 584 20
    $grpWatch.Controls.Add($lblDetail)

    $lblOnOpen = New-Control Label 18 92 140 20 "When this app opens:"
    $grpWatch.Controls.Add($lblOnOpen)

    $cmbOnOpen = New-Control ComboBox 160 88 200 24
    $cmbOnOpen.DropDownStyle = "DropDownList"
    [void]$cmbOnOpen.Items.AddRange(@("Leave watch as it was", "Turn watch ON", "Turn watch OFF"))
    $cmbOnOpen.SelectedIndex = switch ($onOpen) { "on" { 1 } "off" { 2 } default { 0 } }
    $cmbOnOpen.Add_SelectedIndexChanged({
        $value = switch ($cmbOnOpen.SelectedIndex) { 1 { "on" } 2 { "off" } default { $null } }
        try { Set-EnvValue $OnOpenKey $value } catch { Show-Error "Could not save the setting to .env:`n`n$($_.Exception.Message)" }
    })
    $grpWatch.Controls.Add($cmbOnOpen)

    $lblInterval = New-Control Label 380 92 80 20 "Check every:"
    $grpWatch.Controls.Add($lblInterval)

    # Start from the task's current interval (adding it to the list if it's
    # an unusual one); 10 minutes when there's no task yet.
    $currentMinutes = if ($task) { Get-WatchIntervalMinutes $task } else { $null }
    if (-not $currentMinutes) { $currentMinutes = 10 }
    if ($IntervalChoices -notcontains $currentMinutes) {
        $IntervalChoices = @($IntervalChoices + $currentMinutes | Sort-Object)
    }
    $cmbInterval = New-Control ComboBox 462 88 138 24
    $cmbInterval.DropDownStyle = "DropDownList"
    foreach ($m in $IntervalChoices) { [void]$cmbInterval.Items.Add("$m minutes") }
    $cmbInterval.SelectedIndex = [array]::IndexOf($IntervalChoices, $currentMinutes)
    $cmbInterval.Add_SelectedIndexChanged({
        # With no task yet, the choice is just used by "Set up watch".
        if (Get-WatchTask) {
            Set-WatchInterval $IntervalChoices[$cmbInterval.SelectedIndex]
            Update-WatchUI
        }
    })
    $grpWatch.Controls.Add($cmbInterval)

    # --- Folders group
    $grpFolders = New-Control GroupBox 12 144 616 212 "Folders"
    $form.Controls.Add($grpFolders)

    $folderDefs = @(
        @{ Key = "PODCAST_INPUTS_DIR";  Label = "Inputs: drop .md scripts here";            Default = (Join-Path $RepoDir "inputs") },
        @{ Key = "PODCAST_OUTPUTS_DIR"; Label = "Outputs: finished audio goes here";        Default = (Join-Path $RepoDir "outputs") },
        @{ Key = "PODCAST_ARCHIVE_DIR"; Label = "Archive: converted (and failed) scripts";  Default = (Join-Path $RepoDir "script_archive") }
    )

    $i = 0
    foreach ($def in $folderDefs) {
        $y = 22 + $i * 62
        $row = @{ Key = $def.Key; Label = $def.Label; Default = $def.Default }

        $row.Caption = New-Control Label 16 $y 584 18
        $row.Box = New-Control TextBox 16 ($y + 20) 334 24
        $row.Box.ReadOnly = $true
        $btnBrowse = New-Control Button 356 ($y + 19) 80 26 "Browse..."
        $btnOpen   = New-Control Button 440 ($y + 19) 70 26 "Open"
        $row.Reset = New-Control Button 514 ($y + 19) 86 26 "Use default"

        foreach ($b in @($btnBrowse, $btnOpen, $row.Reset)) { $b.Tag = $row }

        $btnBrowse.Add_Click({
            $r = $this.Tag
            $dlg = New-Object System.Windows.Forms.FolderBrowserDialog
            $dlg.Description = $r.Label
            $dlg.ShowNewFolderButton = $true
            if (Test-Path -LiteralPath $r.Box.Text) { $dlg.SelectedPath = $r.Box.Text }
            if ($dlg.ShowDialog($form) -eq [System.Windows.Forms.DialogResult]::OK) {
                $value = if (Test-SamePath $dlg.SelectedPath $r.Default) { $null } else { $dlg.SelectedPath }
                try { Set-EnvValue $r.Key $value } catch { Show-Error "Could not save the folder to .env:`n`n$($_.Exception.Message)" }
                Update-FolderRow $r
            }
        })
        $btnOpen.Add_Click({
            $path = $this.Tag.Box.Text
            try {
                if (-not (Test-Path -LiteralPath $path)) { New-Item -ItemType Directory -Path $path -Force | Out-Null }
                Start-Process explorer.exe -ArgumentList "`"$path`""
            } catch { Show-Error "Could not open $path`n`n$($_.Exception.Message)" }
        })
        $row.Reset.Add_Click({
            $r = $this.Tag
            try { Set-EnvValue $r.Key $null } catch { Show-Error "Could not update .env:`n`n$($_.Exception.Message)" }
            Update-FolderRow $r
        })

        $grpFolders.Controls.AddRange(@($row.Caption, $row.Box, $btnBrowse, $btnOpen, $row.Reset))
        Update-FolderRow $row
        $i++
    }

    $lblNote = New-Control Label 14 368 520 20 "Folder changes take effect on the next run. Settings are saved to .env."
    $lblNote.ForeColor = [System.Drawing.Color]::DimGray
    $form.Controls.Add($lblNote)

    $btnClose = New-Control Button 548 364 80 28 "Close"
    $btnClose.Add_Click({ $form.Close() })
    $form.CancelButton = $btnClose
    $form.Controls.Add($btnClose)

    # --- Menu bar. Added last: shift everything above down to make room.
    $menu = New-Object System.Windows.Forms.MenuStrip
    $mnuAbout = New-Object System.Windows.Forms.ToolStripMenuItem("&About")
    $mnuAbout.Add_Click({ Show-About })
    [void]$menu.Items.Add($mnuAbout)
    $menuHeight = $menu.PreferredSize.Height
    foreach ($c in $form.Controls) { $c.Top += $menuHeight }
    $form.ClientSize = New-Object System.Drawing.Size(
        $form.ClientSize.Width, ($form.ClientSize.Height + $menuHeight))
    $form.MainMenuStrip = $menu
    $form.Controls.Add($menu)

    Update-WatchUI
    [void]$form.ShowDialog()
} catch {
    Show-Error "Podcast Watch hit an error:`n`n$($_.Exception.Message)"
}
