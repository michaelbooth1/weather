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
          [Parameter(Mandatory=$true)][string]$ReleaseSha256,[Parameter(Mandatory=$true)][string]$OwnerSid)
    if($ReleaseSha256 -cnotmatch '^[0-9a-f]{64}$' -or $OwnerSid -notmatch '^S-1-5-21-[0-9-]+$') { throw 'task binding' }
    $psPath=Join-Path ([Environment]::GetFolderPath('System')) 'WindowsPowerShell\v1.0\powershell.exe'
    $wrapper=Join-Path $Release.root 'scripts\ops\lfc_campaign_task.ps1'
    $tokens=@('-NoProfile','-NonInteractive','-File',$wrapper,'-ReleasePath',$ReleasePath,'-ReleaseSha256',$ReleaseSha256)
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
  <Settings><MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy><DisallowStartIfOnBatteries>true</DisallowStartIfOnBatteries><StopIfGoingOnBatteries>false</StopIfGoingOnBatteries><AllowHardTerminate>true</AllowHardTerminate><StartWhenAvailable>false</StartWhenAvailable><RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable><IdleSettings><StopOnIdleEnd>false</StopOnIdleEnd><RestartOnIdle>false</RestartOnIdle></IdleSettings><AllowStartOnDemand>false</AllowStartOnDemand><Enabled>false</Enabled><Hidden>true</Hidden><RunOnlyIfIdle>false</RunOnlyIfIdle><WakeToRun>false</WakeToRun><ExecutionTimeLimit>PT9H</ExecutionTimeLimit><Priority>7</Priority></Settings>
  <Actions Context="Owner"><Exec><Command>$(& $escape $psPath)</Command><Arguments>$(& $escape $arguments)</Arguments><WorkingDirectory>$(& $escape $Release.root)</WorkingDirectory></Exec></Actions>
</Task>
"@
    return $xml
}

function ConvertTo-LfcSafeXml {
    param([Parameter(Mandatory=$true)][string]$Text)
    if($Text.Length -gt 131072) { throw 'task XML size' }
    $settings=[Xml.XmlReaderSettings]::new(); $settings.DtdProcessing=[Xml.DtdProcessing]::Prohibit; $settings.XmlResolver=$null
    $reader=[Xml.XmlReader]::Create([IO.StringReader]::new($Text),$settings)
    try { $document=[Xml.XmlDocument]::new(); $document.XmlResolver=$null; $document.Load($reader); return ,$document }
    finally { $reader.Dispose() }
}

function Assert-LfcCampaignTaskXml {
    param([Parameter(Mandatory=$true)][string]$Actual,[Parameter(Mandatory=$true)][string]$Expected)
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
        $observed=$actualDocument.SelectNodes(('/'+($parts -join '/')),$ns)
        if($observed.Count -ne 1 -or $observed[0].InnerText -cne $parent.InnerText) { throw ('task property mismatch '+$parent.LocalName) }
    }
    $enabled=$actualDocument.SelectSingleNode('/t:Task/t:Settings/t:Enabled',$ns)
    if($null -eq $enabled -or $enabled.InnerText -cnotin @('true','false')) { throw 'task enabled unreadable' }
    return ($enabled.InnerText -ceq 'true')
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
