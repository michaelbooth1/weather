# Owner-run only: narrowly scoped inbound rule for the read-only LAN service.
[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'Medium')]
param(
    [Parameter(Mandatory = $true)][string]$AllowIp,
    [ValidateRange(1, 65535)][int]$Port = 8765,
    [switch]$Unregister
)
$ErrorActionPreference = 'Stop'
$address = $null
if (-not [Net.IPAddress]::TryParse($AllowIp, [ref]$address) -or
    $address.AddressFamily -ne [Net.Sockets.AddressFamily]::InterNetwork -or
    $address.ToString() -cne $AllowIp) {
    throw 'AllowIp must be a literal RFC1918 IPv4 address.'
}
$bytes = $address.GetAddressBytes()
if (-not ($bytes[0] -eq 10 -or ($bytes[0] -eq 172 -and $bytes[1] -ge 16 -and $bytes[1] -le 31) -or
          ($bytes[0] -eq 192 -and $bytes[1] -eq 168))) {
    throw 'AllowIp must be RFC1918.'
}
$ruleName = "WeatherWalletReader-$AllowIp-$Port"
if ($Unregister) {
    if ($PSCmdlet.ShouldProcess($ruleName, 'Remove wallet-reader firewall rule')) {
        Remove-NetFirewallRule -Name $ruleName -ErrorAction Stop
    }
} else {
    if ($PSCmdlet.ShouldProcess($ruleName, 'Register inbound TCP rule for one remote IP on Private profile')) {
        if (Get-NetFirewallRule -Name $ruleName -ErrorAction SilentlyContinue) {
            throw 'Rule already exists; unregister this exact rule before replacing it.'
        }
        New-NetFirewallRule -Name $ruleName -DisplayName $ruleName -Direction Inbound -Action Allow `
            -Protocol TCP -LocalPort $Port -RemoteAddress $AllowIp -Profile Private -Enabled True | Out-Null
    }
}
