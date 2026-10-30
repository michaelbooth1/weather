# Test isolation for scheduled-task registrars (dot-source, then call before any Scheduler call).
#
# While WEATHER_TASK_TEST is set, a registrar refuses to run unless every Scheduler command it is
# about to use resolves to a script-defined stub: a function with no owning module. The real
# ScheduledTasks commands are CDXML *functions* owned by the ScheduledTasks module (they autoload on
# first use), so "is a function" alone does not prove a stub. Reading the function: drive never
# autoloads a module. Unset (production), this is a no-op.
function Assert-WeatherScheduledTaskTestIsolation {
    param([Parameter(Mandatory = $true)][string[]]$Command)
    if ([string]::IsNullOrEmpty($env:WEATHER_TASK_TEST)) { return }
    foreach ($name in $Command) {
        $stub = Get-Item -LiteralPath ('function:\' + $name) -ErrorAction SilentlyContinue
        if ($null -eq $stub -or -not [string]::IsNullOrEmpty([string]$stub.ModuleName)) {
            throw ('WEATHER_TASK_TEST is set: refusing to reach the real Task Scheduler; ' +
                $name + ' is not a test stub')
        }
    }
}
