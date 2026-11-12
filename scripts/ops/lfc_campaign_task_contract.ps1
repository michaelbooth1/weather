# Read-only task contract. Dot-sourcing defines pure XML construction/validation.
param([Alias('Action')][ValidateSet('Read')][string]$ContractAction,
      [Alias('ReleasePath')][string]$ContractReleasePath,[Alias('ReleaseSha256')][string]$ContractReleaseSha256)
Set-StrictMode -Version 2.0
$ErrorActionPreference='Stop'

function Assert-LfcCampaignImportEnvironment {
    # Refuse names before Python bootstrap can inspect a redirected registry or
    # import a different checkout. Never print inherited variable values.
    foreach($name in @('PYTHONPATH','PYTHONHOME','WEATHER_MARKET_REGISTRY')) {
        if(Test-Path -LiteralPath ('Env:\'+$name)) { throw ('campaign ambient override refused: '+$name) }
    }
}

function ConvertTo-LfcTaskArguments {
    param([string[]]$Tokens)
    $items=foreach($token in $Tokens) {
        $value=([string]$token -replace '(\\*)"','$1$1\"') -replace '(\\+)$','$1$1'
        '"'+$value+'"'
    }
    return ($items -join ' ')
}

function New-LfcCampaignTaskXml {
    param([Parameter(Mandatory=$true)]$Release,[Parameter(Mandatory=$true)][string]$ReleasePath,
          [Parameter(Mandatory=$true)][string]$ReleaseSha256,[Parameter(Mandatory=$true)][string]$OwnerSid,
          [ValidateSet('PT9H','PT11H')][string]$ExecutionTimeLimit='PT11H')
    if($ReleaseSha256 -cnotmatch '^[0-9a-f]{64}$' -or $OwnerSid -notmatch '^S-1-5-21-[0-9-]+$') { throw 'task binding' }
    # A GUI-subsystem interpreter creates no console at all. Its repository
    # launcher waits for a CREATE_NO_WINDOW wrapper and returns its exit code.
    # InteractiveToken keeps owner toasts in the owner's desktop session.
    $hostPath=$Release.windowless.python
    $launcher=Join-Path $Release.root 'scripts\ops\lfc_campaign_windowless.py'
    $tokens=@('-I',$launcher,'--release',$ReleasePath,'--release-sha256',$ReleaseSha256)
    $arguments=ConvertTo-LfcTaskArguments -Tokens $tokens
    $escape={param($value) [Security.SecurityElement]::Escape([string]$value)}
    # Finite generic ticks permit supported policy edits without re-registration.
    # Floating local boundaries follow the repository Scheduler contract. These
    # are generic timer ticks only: the controller's explicit UTC windows and
    # named Toronto dates alone authorize go. IgnoreNew supplements date claims.
    $xml=@"
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>Owner activated finite LFC campaign; no agent activation.</Description></RegistrationInfo>
  <Triggers><TimeTrigger><Repetition><Interval>PT5M</Interval><Duration>P52D</Duration><StopAtDurationEnd>false</StopAtDurationEnd></Repetition><StartBoundary>2026-11-10T00:00:00</StartBoundary><EndBoundary>2027-01-01T00:00:00</EndBoundary><Enabled>true</Enabled></TimeTrigger></Triggers>
  <Principals><Principal id="Owner"><UserId>$(& $escape $OwnerSid)</UserId><LogonType>InteractiveToken</LogonType><RunLevel>LeastPrivilege</RunLevel></Principal></Principals>
  <Settings><MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy><DisallowStartIfOnBatteries>true</DisallowStartIfOnBatteries><StopIfGoingOnBatteries>false</StopIfGoingOnBatteries><AllowHardTerminate>true</AllowHardTerminate><StartWhenAvailable>false</StartWhenAvailable><RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable><IdleSettings><StopOnIdleEnd>false</StopOnIdleEnd><RestartOnIdle>false</RestartOnIdle></IdleSettings><AllowStartOnDemand>false</AllowStartOnDemand><Enabled>false</Enabled><Hidden>true</Hidden><RunOnlyIfIdle>false</RunOnlyIfIdle><WakeToRun>false</WakeToRun><ExecutionTimeLimit>$ExecutionTimeLimit</ExecutionTimeLimit><Priority>7</Priority></Settings>
  <Actions Context="Owner"><Exec><Command>$(& $escape $hostPath)</Command><Arguments>$(& $escape $arguments)</Arguments><WorkingDirectory>$(& $escape $Release.root)</WorkingDirectory></Exec></Actions>
</Task>
"@
    return $xml
}

function Assert-LfcCampaignUpgrade {
    param([Parameter(Mandatory=$true)]$Previous,[Parameter(Mandatory=$true)][string]$CampaignPath,
          [Parameter(Mandatory=$true)][bool]$Enabled,[Parameter(Mandatory=$true)][string]$State,
          $Successor=$null)
    if($Enabled -or $State -cne 'Disabled') { throw 'upgrade requires disabled, non-running task; wait for normal cleanup' }
    if([IO.Path]::GetFullPath($CampaignPath) -cne [IO.Path]::GetFullPath($Previous.campaign_path)) { throw 'upgrade campaign path changed' }
    if($null -ne $Successor) {
        foreach($key in @('maker_address','ledger_genesis_sha256','state_id','host_id','principal_id','campaign_path','task_name')) {
            if(([string]$Previous.$key).ToLowerInvariant() -cne ([string]$Successor.$key).ToLowerInvariant()) { throw ('upgrade identity changed: '+$key) }
        }
    }
    return $true
}

function ConvertTo-LfcSafeXml {
    param([Parameter(Mandatory=$true)][string]$Text)
    if($Text.Length -gt 131072) { throw 'task XML size' }
    $settings=[Xml.XmlReaderSettings]::new(); $settings.DtdProcessing=[Xml.DtdProcessing]::Prohibit; $settings.XmlResolver=$null
    $reader=[Xml.XmlReader]::Create([IO.StringReader]::new($Text),$settings)
    try { $document=[Xml.XmlDocument]::new(); $document.XmlResolver=$null; $document.Load($reader); return ,$document }
    finally { $reader.Dispose() }
}

function Read-LfcCampaignPolicyBytes {
    param([Parameter(Mandatory=$true)][string]$CampaignPath)
    $file=Get-Item -LiteralPath $CampaignPath -ErrorAction Stop
    if($file.Length -gt 65536 -or ($file.Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'campaign file' }
    $stream=[IO.File]::Open($CampaignPath,[IO.FileMode]::Open,[IO.FileAccess]::Read,([IO.FileShare]::ReadWrite -bor [IO.FileShare]::Delete))
    try {
        $reader=[IO.BinaryReader]::new($stream)
        $bytes=$reader.ReadBytes(65537)
        if($bytes.Length -gt 65536) { throw 'campaign file size' }
        return ,$bytes
    } finally { $stream.Dispose() }
}

function ConvertTo-LfcCampaignUtcInstant {
    param([Parameter(Mandatory=$true)]$Value)
    if($Value -is [DateTimeOffset]) { return $Value.ToUniversalTime() }
    if($Value -is [DateTime]) {
        if($Value.Kind -eq [DateTimeKind]::Unspecified) { throw 'campaign timestamp requires an offset' }
        return ([DateTimeOffset]$Value).ToUniversalTime()
    }
    if($Value -isnot [string] -or $Value -notmatch '(?:Z|[+-][0-9]{2}:[0-9]{2})$') {
        throw 'campaign timestamp requires an offset'
    }
    return ([DateTimeOffset]::Parse($Value,[Globalization.CultureInfo]::InvariantCulture)).ToUniversalTime()
}

function Get-LfcCampaignLaunch {
    param([Parameter(Mandatory=$true)][string]$CampaignPath,$NowUtc=[DateTimeOffset]::UtcNow,
          $TaskStartedUtc=$NowUtc)
    # Pure helper callers may omit task start; the real wrapper requires it.
    # Preserve awareness before conversion, then compare/bound UTC instants.
    $NowUtc=ConvertTo-LfcCampaignUtcInstant -Value $NowUtc
    $TaskStartedUtc=ConvertTo-LfcCampaignUtcInstant -Value $TaskStartedUtc
    # The digest and deadline use ONE bounded byte snapshot. An unreadable
    # policy gets a short reporting budget and can never authorize admission.
    try { $bytes=Read-LfcCampaignPolicyBytes -CampaignPath $CampaignPath } catch { $bytes=[byte[]]@() }
    $hasher=[Security.Cryptography.SHA256]::Create()
    try { $sha=([BitConverter]::ToString($hasher.ComputeHash($bytes))).Replace('-','').ToLowerInvariant() }
    finally { $hasher.Dispose() }
    $deadline=Get-LfcCampaignDeadline -CampaignPath $CampaignPath -NowUtc $NowUtc -PolicyBytes $bytes
    if($TaskStartedUtc -gt $NowUtc) { throw 'campaign task start time' }
    $schedulerEnd=$TaskStartedUtc.AddHours(11)
    if($schedulerEnd -lt $deadline) { $deadline=$schedulerEnd }
    return [pscustomobject]@{deadline_utc=$deadline.ToString('o');policy_bytes_sha256=$sha}
}

function Get-LfcCampaignDeadline {
    param([Parameter(Mandatory=$true)][string]$CampaignPath,
          [DateTimeOffset]$NowUtc=[DateTimeOffset]::UtcNow,[AllowEmptyCollection()][byte[]]$PolicyBytes)
    # This only bounds the wrapper. The child independently parses every field
    # before admission; malformed policy gets at most 30 minutes to report REFUSED.
    $fallback=$NowUtc.AddMinutes(30)
    try {
        $bytes=if($PSBoundParameters.ContainsKey('PolicyBytes')){$PolicyBytes}else{Read-LfcCampaignPolicyBytes -CampaignPath $CampaignPath}
        if($bytes.Length -gt 65536) { return $fallback }
        $policyRow=ConvertFrom-Json -InputObject ([Text.Encoding]::UTF8.GetString($bytes).TrimStart([char]0xFEFF))
        $zone=[TimeZoneInfo]::FindSystemTimeZoneById('Eastern Standard Time')
        $localNow=[TimeZoneInfo]::ConvertTime($NowUtc,$zone)
        $culture=[Globalization.CultureInfo]::InvariantCulture
        $end=$null
        if($policyRow.schema_version -cin @('lfc_campaign_policy_v0.2','lfc_campaign_policy_v0.3','lfc_campaign_policy_v0.4')) {
            if(@($policyRow.start_window_toronto).Count -ne 2) { return $fallback }
            $begin=[TimeSpan]::ParseExact([string]$policyRow.start_window_toronto[0],'hh\:mm\:ss',$culture)
            $finish=[TimeSpan]::ParseExact([string]$policyRow.start_window_toronto[1],'hh\:mm\:ss',$culture)
            $stop=[TimeSpan]::ParseExact([string]$policyRow.trading_end_toronto,'hh\:mm\:ss',$culture)
            if($begin -ge $finish -or $finish -ge $stop) { return $fallback }
            # IgnoreNew drops timer ticks while a pre-entry child is working.
            # Give near-window ticks the SAME latest-go cleanup envelope; this
            # extends their containment budget, never the child's entry window.
            $lookback=[TimeSpan]::FromMinutes([math]::Max(5,30-($finish-$begin).TotalMinutes))
            $entryDay=$localNow.Date
            # A midnight window's lookback belongs to the previous local date.
            if($begin -lt $lookback -and $localNow.TimeOfDay -ge $finish) { $entryDay=$entryDay.AddDays(1) }
            $warmLocal=[DateTime]::SpecifyKind($entryDay.Add($begin).Subtract($lookback),[DateTimeKind]::Unspecified)
            $latestLocal=[DateTime]::SpecifyKind($entryDay.Add($finish),[DateTimeKind]::Unspecified)
            $warm=[DateTimeOffset]::new([TimeZoneInfo]::ConvertTimeToUtc($warmLocal,$zone))
            $latest=[DateTimeOffset]::new([TimeZoneInfo]::ConvertTimeToUtc($latestLocal,$zone))
            if($NowUtc -lt $warm -or $NowUtc -ge $latest) { return $fallback }
            $localStop=[DateTime]::SpecifyKind($entryDay.Add($stop),[DateTimeKind]::Unspecified)
            $fixed=[DateTimeOffset]::new([TimeZoneInfo]::ConvertTimeToUtc($localStop,$zone))
            if($policyRow.schema_version -ceq 'lfc_campaign_policy_v0.4') {
                # The earliest tick receiving a full envelope must also fit
                # Scheduler PT11H. Python uses this same conservative bound.
                $contained=$warm.AddHours(11).AddMinutes(-30)
                if($contained -lt $fixed) { $fixed=$contained }
            }
            $seconds=[int]$policyRow.max_session_seconds
            $maximum=if($policyRow.schema_version -ceq 'lfc_campaign_policy_v0.4'){35100}else{21600}
            if($seconds -lt 300 -or $seconds -gt $maximum) { return $fallback }
            # Admission and client setup may use any part of this window.
            # Bound the latest possible child end, never wrapper launch time.
            $end=$latest.AddSeconds($seconds)
            if($fixed -lt $end) { $end=$fixed }
        } elseif($policyRow.schema_version -ceq 'lfc_campaign_policy_v0.1') {
            foreach($entry in $policyRow.entries) {
                $start=[DateTimeOffset]::Parse([string]$entry.window_start_utc,$culture)
                $finish=[DateTimeOffset]::Parse([string]$entry.window_end_utc,$culture)
                $lookback=[TimeSpan]::FromMinutes([math]::Max(5,30-($finish-$start).TotalMinutes))
                if($start.Subtract($lookback) -le $NowUtc -and $NowUtc -lt $finish) {
                    $seconds=[math]::Min([int]$entry.duration_seconds,[int]$policyRow.max_session_seconds)
                    if($seconds -lt 300 -or $seconds -gt 21600) { return $fallback }
                    $end=$finish.AddSeconds($seconds)
                    if($policyRow.trading_end_toronto) {
                        $stop=[TimeSpan]::ParseExact([string]$policyRow.trading_end_toronto,'hh\:mm\:ss',$culture)
                        $entryLocal=[TimeZoneInfo]::ConvertTime($start,$zone)
                        $localStop=[DateTime]::SpecifyKind($entryLocal.Date.Add($stop),[DateTimeKind]::Unspecified)
                        $fixed=[DateTimeOffset]::new([TimeZoneInfo]::ConvertTimeToUtc($localStop,$zone))
                        if($fixed -lt $end) { $end=$fixed }
                    }
                    break
                }
            }
        }
        if($null -eq $end -or $end -le $NowUtc) { return $fallback }
        return $end.AddMinutes(30)
    } catch { return $fallback }
}

function Assert-LfcCampaignTaskXml {
    param([Parameter(Mandatory=$true)][string]$Actual,[Parameter(Mandatory=$true)][string]$Expected)
    # Scheduler exports omit these default values. Only an absent element at
    # this exact path can match its exact default; present values stay strict.
    $defaults=[Collections.Generic.Dictionary[string,string]]::new([StringComparer]::Ordinal)
    $defaults['/t:Task/t:Triggers/t:TimeTrigger/t:Repetition/t:StopAtDurationEnd']='false'
    $defaults['/t:Task/t:Triggers/t:TimeTrigger/t:Enabled']='true'
    $defaults['/t:Task/t:Settings/t:AllowHardTerminate']='true'
    $defaults['/t:Task/t:Settings/t:StartWhenAvailable']='false'
    $defaults['/t:Task/t:Settings/t:RunOnlyIfNetworkAvailable']='false'
    $defaults['/t:Task/t:Settings/t:RunOnlyIfIdle']='false'
    $defaults['/t:Task/t:Settings/t:WakeToRun']='false'
    $defaults['/t:Task/t:Settings/t:Priority']='7'
    $defaults['/t:Task/t:Principals/t:Principal/t:RunLevel']='LeastPrivilege'
    $actualDocument=ConvertTo-LfcSafeXml $Actual; $expectedDocument=ConvertTo-LfcSafeXml $Expected
    $ns=[Xml.XmlNamespaceManager]::new($actualDocument.NameTable); $ns.AddNamespace('t','http://schemas.microsoft.com/windows/2004/02/mit/task')
    $en=[Xml.XmlNamespaceManager]::new($expectedDocument.NameTable); $en.AddNamespace('t','http://schemas.microsoft.com/windows/2004/02/mit/task')
    foreach($path in @('/t:Task/t:Actions/t:Exec','/t:Task/t:Principals/t:Principal','/t:Task/t:Triggers/t:TimeTrigger')) {
        if($actualDocument.SelectNodes($path,$ns).Count -ne 1) { throw 'task cardinality' }
    }
    if($actualDocument.SelectNodes('/t:Task/t:Actions/*',$ns).Count -ne 1 -or
       $actualDocument.SelectNodes('/t:Task/t:Triggers/*',$ns).Count -ne 1 -or
       $actualDocument.SelectNodes('/t:Task/t:Settings/t:RestartOnFailure',$ns).Count -ne 0) { throw 'task extra capability' }
    foreach($node in $expectedDocument.SelectNodes('//text()',$en)) {
        $parent=$node.ParentNode
        if($parent.Name -eq 'Description' -or ($parent.Name -eq 'Enabled' -and $parent.ParentNode.Name -eq 'Settings')) { continue }
        $parts=@(); $cursor=$parent
        while($cursor -is [Xml.XmlElement]) { $parts=@('t:'+$cursor.LocalName)+$parts; $cursor=$cursor.ParentNode }
        $path='/'+($parts -join '/')
        $observed=$actualDocument.SelectNodes($path,$ns)
        if($observed.Count -eq 0 -and $defaults.ContainsKey($path) -and $parent.InnerText -ceq $defaults[$path]) { continue }
        if($observed.Count -ne 1 -or $observed[0].InnerText -cne $parent.InnerText) { throw ('task property mismatch '+$parent.LocalName) }
    }
    # Scheduler omits Settings/Enabled when enabled (its schema default).
    $enabled=$actualDocument.SelectNodes('/t:Task/t:Settings/t:Enabled',$ns)
    if($enabled.Count -eq 0) { return $true }
    if($enabled.Count -ne 1 -or $enabled[0].InnerText -cnotin @('true','false')) { throw 'task enabled unreadable' }
    return ($enabled[0].InnerText -ceq 'true')
}

function Read-LfcCampaignRelease {
    param([Parameter(Mandatory=$true)][string]$Path,[Parameter(Mandatory=$true)][string]$Sha256)
    if($Sha256 -cnotmatch '^[0-9a-f]{64}$' -or (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant() -cne $Sha256) { throw 'release hash' }
    $file=Get-Item -LiteralPath $Path
    if($file.Length -gt 65536 -or ($file.Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'release file' }
    $release=ConvertFrom-Json -InputObject ([IO.File]::ReadAllText($Path))
    if($release.schema_version -cne 'lfc_campaign_release_v0.1' -or $release.task_name -cne 'WeatherLFCCampaign') { throw 'release schema' }
    return $release
}

if($MyInvocation.InvocationName -ne '.' -and $ContractAction) {
    $release=Read-LfcCampaignRelease -Path $ContractReleasePath -Sha256 $ContractReleaseSha256
    $sid=[Security.Principal.WindowsIdentity]::GetCurrent().User.Value
    $expected=New-LfcCampaignTaskXml -Release $release -ReleasePath $ContractReleasePath -ReleaseSha256 $ContractReleaseSha256 -OwnerSid $sid
    $actual=Export-ScheduledTask -TaskName $release.task_name -TaskPath '\' -ErrorAction Stop
    $enabled=Assert-LfcCampaignTaskXml -Actual $actual -Expected $expected
    @{schema_version='lfc_campaign_task_read_v0.1';definition_valid=$true;enabled=[bool]$enabled;release_sha256=$ContractReleaseSha256} | ConvertTo-Json -Compress
}
