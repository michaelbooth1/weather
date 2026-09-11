# Direct verified private uploads

The owner replaced the encrypted campaign with a simpler task on September 11:
upload approved data without content encryption, independently download and
compare SHA-256 hashes, then delete only the matching originals. Retain a
simple source-to-Drive-object record. Existing encrypted archives remain
recoverable through their retained records and keys.

The workstation's existing upload-and-download helper accepts `--plain-file`
for a copied input under `scratch/ac-in`, up to 1100 MiB. Invoke it through
`workstation_cold_archive_stage --backup-recovery --plain-file` with the exact
input SHA-256 and private Drive destination. It uploads the original file
bytes; the stored credential configuration remains protected separately.

Capture host resource admission and exact-source deletion checks still apply.
The earlier multi-phase encrypted controller is not the current execution route.

## Update this file when

Update when the approved transfer or original-deletion route changes.
