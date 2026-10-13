# Owner-run only: scoped inbound rule for the read-only LAN service.
# -AllowIp given: the rule admits that one remote RFC1918 IPv4 (rule WeatherWalletReader-<ip>-<port>).
# -AllowIp omitted: the rule admits the three RFC1918 ranges (rule WeatherWalletReader-anylan-<port>),
# matching serve's default any-LAN admission (owner decision 2026-10-09). Same-machine callers are
# not filtered by an inbound rule either way. Private profile only.
[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'Medium')]
param(
    [string]$AllowIp = '',
    [ValidateRange(1, 65535)][int]$Port = 8765,
    [switch]$Unregister
)
$ErrorActionPreference = 'Stop'
if ($AllowIp) {
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
    $remote = @($AllowIp)
    $ruleName = "WeatherWalletReader-$AllowIp-$Port"
} else {
    $remote = @('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16')
    $ruleName = "WeatherWalletReader-anylan-$Port"
}
if ($Unregister) {
    if ($PSCmdlet.ShouldProcess($ruleName, 'Remove wallet-reader firewall rule')) {
        Remove-NetFirewallRule -Name $ruleName -ErrorAction Stop
    }
} else {
    if ($PSCmdlet.ShouldProcess($ruleName, ('Register inbound TCP rule for remote {0} on Private profile' -f ($remote -join ',')))) {
        if (Get-NetFirewallRule -Name $ruleName -ErrorAction SilentlyContinue) {
            throw 'Rule already exists; unregister this exact rule before replacing it.'
        }
        New-NetFirewallRule -Name $ruleName -DisplayName $ruleName -Direction Inbound -Action Allow `
            -Protocol TCP -LocalPort $Port -RemoteAddress $remote -Profile Private -Enabled True | Out-Null
    }
}
