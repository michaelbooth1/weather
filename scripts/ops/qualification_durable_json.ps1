# Create-once split evidence. A claim/partial survives every failed publication.
Set-StrictMode -Version Latest

function Write-WeatherQualificationImmutableJson {
    param([Parameter(Mandatory = $true)][string]$Path, [Parameter(Mandatory = $true)]$Payload)
    if (-not ('Weather.Operations.QualificationPublication' -as [type])) {
        Add-Type -TypeDefinition @'
using System;
using System.ComponentModel;
using System.IO;
using System.Runtime.InteropServices;
namespace Weather.Operations {
    public static class QualificationPublication {
        [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
        private static extern bool MoveFileEx(string source, string target, uint flags);
        public static void Write(string target, byte[] bytes) {
            if (!Path.IsPathRooted(target) || target.StartsWith(@"\\"))
                throw new InvalidOperationException("Local absolute publication path required");
            target = Path.GetFullPath(target);
            if (bytes.Length < 1 || bytes.Length > 2097152)
                throw new InvalidOperationException("Publication exceeds the metadata bound");
            for (DirectoryInfo parent = new DirectoryInfo(Path.GetDirectoryName(target)); parent != null; parent = parent.Parent) {
                if (!parent.Exists || (parent.Attributes & FileAttributes.ReparsePoint) != 0)
                    throw new InvalidOperationException("Missing or redirected publication parent");
            }
            // The fixed claim prevents retries after any interruption, even if
            // no final JSON appeared. Never remove claims or partial evidence.
            using (FileStream claim = new FileStream(target + ".publish-claim", FileMode.CreateNew, FileAccess.Write, FileShare.None)) {
                claim.WriteByte(1); claim.Flush(true);
            }
            if (File.Exists(target)) throw new IOException("Immutable target already exists");
            string partial = target + ".partial";
            using (FileStream output = new FileStream(partial, FileMode.CreateNew, FileAccess.Write, FileShare.None)) {
                output.Write(bytes, 0, bytes.Length); output.Flush(true);
            }
            // MOVEFILE_WRITE_THROUGH only: neither replacement nor cross-volume
            // copy is permitted. The complete target becomes visible atomically.
            if (!MoveFileEx(partial, target, 8)) throw new Win32Exception(Marshal.GetLastWin32Error());
        }
    }
}
'@
    }
    $json = ConvertTo-Json -InputObject $Payload -Depth 80 -Compress
    $bytes = [Text.UTF8Encoding]::new($false, $true).GetBytes($json + "`n")
    [Weather.Operations.QualificationPublication]::Write($Path, $bytes)
}
