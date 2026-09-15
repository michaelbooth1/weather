"""Actual disposable S4U invocation on hosted Windows, never the capture host."""

import os
from pathlib import Path
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(
    os.name != "nt" or os.environ.get("GITHUB_ACTIONS") != "true" or os.environ.get("RUNNER_ENVIRONMENT") != "github-hosted",
    reason="requires disposable GitHub-hosted Windows Scheduler, not a user or capture installation")


def test_actual_s4u_measurement_task_binds_native_token_command_and_engine(tmp_path):
    quote = lambda value: "'" + str(value).replace("'", "''") + "'"
    script = tmp_path / "test-parent.ps1"
    script.write_text("$ErrorActionPreference='Stop'\n$root=" + quote(ROOT) + "\n$fixture=" + quote(tmp_path) + r'''
. (Join-Path $root 'scripts/ops/integration_attempt_contract.ps1')
. (Join-Path $root 'scripts/ops/workload_admission.ps1')
$id=[Guid]::NewGuid().ToString('N')
$name='WeatherQualificationMeasure_'+$id
$driver=Join-Path $fixture 'driver.ps1'
$requestPath=Join-Path $fixture 'request.json'
$resultPath=Join-Path $fixture 'result.json'
$at=(Get-Date).AddMinutes(2).ToString('yyyy-MM-ddTHH:mm:ss')
$account='wq'+$id.Substring(0,12)
$userCreated=$false
try {
    if(Get-LocalUser -Name $account -ErrorAction SilentlyContinue){throw 'fixture account collision'}
    $fixturePassword=ConvertTo-SecureString (([Guid]::NewGuid().ToString('N'))+'aA!9') -AsPlainText -Force
    $fixtureUser=New-LocalUser -Name $account -Password $fixturePassword -AccountNeverExpires -PasswordNeverExpires -Description 'Disposable qualification S4U CI fixture'
    $userCreated=$true
    Add-LocalGroupMember -SID 'S-1-5-32-545' -Member $fixtureUser
    $sid=[string]$fixtureUser.SID.Value
    $acl=Get-Acl -LiteralPath $fixture
    $acl.SetAccessRule([Security.AccessControl.FileSystemAccessRule]::new($fixtureUser.SID,'FullControl','ContainerInherit,ObjectInherit','None','Allow'))
    Set-Acl -LiteralPath $fixture -AclObject $acl
    $controllerRoot=Join-Path $fixture 'controller'
    $scripts=Join-Path $controllerRoot 'scripts/ops';[void][IO.Directory]::CreateDirectory($scripts)
    foreach($file in @('integration_attempt_contract.ps1','workload_admission.ps1','qualification_host_identity.ps1','measure_split_qualification.ps1')){
        Copy-Item -LiteralPath (Join-Path $root ('scripts/ops/'+$file)) -Destination (Join-Path $scripts $file)
    }
    $hashing=[Security.Cryptography.SHA256]::Create()
    try{$principal=-join($hashing.ComputeHash([Text.Encoding]::UTF8.GetBytes("international_live_execution_principal_v1`0"+$sid.ToLowerInvariant())) | ForEach-Object{$_.ToString('x2')})}finally{$hashing.Dispose()}
$request=[ordered]@{measurement_id=$id;repo_root=$fixture
    plan=@{host_id=(Get-WeatherExecutionHostId);principal_id=$principal;not_before=$at}
    task=@{name=$name;user_sid=$sid}}
[IO.File]::WriteAllText($requestPath,($request | ConvertTo-Json -Depth 10),[Text.UTF8Encoding]::new($false))
$hash=(Get-FileHash -LiteralPath $requestPath -Algorithm SHA256).Hash.ToLowerInvariant()
$preamble=@'
param([string]$RequestPath,[string]$ExpectedRequestSha256)
$ErrorActionPreference='Stop'
'@
$body=@'
. (Join-Path $root 'scripts/ops/integration_attempt_contract.ps1')
. (Join-Path $root 'scripts/ops/workload_admission.ps1')
. (Join-Path $root 'scripts/ops/qualification_host_identity.ps1')
try {
    if((Get-FileHash -LiteralPath $RequestPath -Algorithm SHA256).Hash.ToLowerInvariant() -cne $ExpectedRequestSha256){throw 'request changed'}
    $tokens=$null;$errors=$null
    $ast=[Management.Automation.Language.Parser]::ParseFile((Join-Path $root 'scripts/ops/measure_split_qualification.ps1'),[ref]$tokens,[ref]$errors)
    if($errors.Count){throw ($errors | Out-String)}
    $function=$ast.Find({param($node)$node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -ceq 'Assert-WeatherMeasurementInvocation'},$true)
    Invoke-Expression $function.Extent.Text
    $request=Get-Content -LiteralPath $RequestPath -Raw | ConvertFrom-Json
    $result=Assert-WeatherMeasurementInvocation -Request $request -Path $RequestPath -Sha256 $ExpectedRequestSha256 -Script $PSCommandPath
    $wrong=$false
    try{Assert-WeatherMeasurementInvocation -Request $request -Path $RequestPath -Sha256 ('f'*64) -Script $PSCommandPath | Out-Null}
    catch{$wrong=$true}
    if(-not $wrong){throw 'wrong registered command was accepted'}
    [IO.File]::WriteAllText((Join-Path (Split-Path -Parent $RequestPath) 'result.json'),($result | ConvertTo-Json -Depth 10),[Text.UTF8Encoding]::new($false))
}catch{
    [IO.File]::WriteAllText((Join-Path (Split-Path -Parent $RequestPath) 'failure.txt'),($_ | Out-String),[Text.UTF8Encoding]::new($false))
    exit 1
}
'@
$quotedRoot="'" + $controllerRoot.Replace("'","''") + "'"
[IO.File]::WriteAllText($driver,($preamble+"`n"+'$root='+$quotedRoot+"`n"+$body),[Text.UTF8Encoding]::new($false))
$exe=Join-Path $PSHOME 'powershell.exe'
$arguments=ConvertTo-WeatherIntegrationScheduledTaskArgumentString -Tokens @('-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',$driver,
    '-RequestPath',$requestPath,'-ExpectedRequestSha256',$hash)
$scheduler=New-Object -ComObject 'Schedule.Service';$scheduler.Connect()
$definition=$scheduler.NewTask(0)
$definition.Principal.UserId=$env:COMPUTERNAME+'\'+$account
$definition.Principal.LogonType=2
$definition.Principal.RunLevel=0
$action=$definition.Actions.Create(0)
$action.Path=$exe;$action.Arguments=$arguments;$action.WorkingDirectory=$fixture
$trigger=$definition.Triggers.Create(1);$trigger.StartBoundary=$at
$definition.Settings.MultipleInstances=2
$definition.Settings.StartWhenAvailable=$false
$definition.Settings.ExecutionTimeLimit='PT34M'
$registered=$false
try {
    if(Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue){throw 'disposable task name collision'}
    # Cross-account S4U registration requires its password; Scheduler does not
    # retain it. The random fixture credential is never printed or written.
    $credential=[Management.Automation.PSCredential]::new($definition.Principal.UserId,$fixturePassword)
    [void]$scheduler.GetFolder('\').RegisterTaskDefinition($name,$definition,2,$definition.Principal.UserId,$credential.GetNetworkCredential().Password,2,$null)
    $registered=$true
    Start-ScheduledTask -TaskName $name
    $clock=[Diagnostics.Stopwatch]::StartNew()
    while(-not (Test-Path -LiteralPath $resultPath) -and -not (Test-Path -LiteralPath (Join-Path $fixture 'failure.txt')) -and $clock.Elapsed.TotalSeconds -lt 45){Start-Sleep -Milliseconds 200}
    if(Test-Path -LiteralPath (Join-Path $fixture 'failure.txt')){throw ([IO.File]::ReadAllText((Join-Path $fixture 'failure.txt')))}
    if(-not (Test-Path -LiteralPath $resultPath)){throw ('S4U fixture produced no result: '+((Get-ScheduledTaskInfo -TaskName $name) | Out-String))}
    $value=Get-Content -LiteralPath $resultPath -Raw | ConvertFrom-Json
    if($value.token.logon_type -ne 4 -or $value.token.token_type -ne 1 -or $value.token.elevated -or
        $value.engine_pid -notin @($value.ancestry.pid) -or $value.task_xml_sha256 -cnotmatch '^[0-9a-f]{64}$'){throw 'native S4U fixture is incomplete'}
} finally {
    if($registered){
        $task=Get-ScheduledTask -TaskName $name
        if($task.Actions.Count -ne 1 -or $task.Actions[0].Arguments -cne $arguments){throw 'fixture task changed; refuse cleanup'}
        if([string]$task.State -eq 'Running'){Stop-ScheduledTask -InputObject $task}
        Unregister-ScheduledTask -InputObject $task -Confirm:$false
    }
}
} finally {
    if($userCreated){
        $retained=Get-LocalUser -Name $account -ErrorAction Stop
        if([string]$retained.SID.Value -cne $sid){throw 'fixture account identity changed; refuse cleanup'}
        Remove-LocalUser -InputObject $retained
    }
}
''', encoding="utf-8")
    executable = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    result = subprocess.run([str(executable), "-NoProfile", "-NonInteractive", "-File", str(script)],
                            capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr
