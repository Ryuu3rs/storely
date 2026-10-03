# Security

Storely installs software and runs a small part of itself as admin (and, for one clean-up job, as SYSTEM), so
security reports are very welcome.

## Reporting a problem

Please use GitHub's **private vulnerability reporting** (Security tab > Report a vulnerability) rather than a
public issue. Include what you did, what happened, and the Storely version (Settings > About). You'll get a reply
within a week.

## How Storely protects you

- **Packages**: Store packages must come from a Microsoft address, match Microsoft's published digest, and carry a
  valid signature from the Microsoft Marketplace CA or Microsoft's own code-signing CAs, from the same publisher as
  the copy you have. Desktop installers must match the SHA-256 in the Store's install recipe and be validly signed.
- **Admin rights**: the elevated helper is the installed program itself (Program Files, admin-only). Storely
  refuses to ask for admin from a copy that standard users can modify. No scripts are written to disk; every input
  is validated. SYSTEM work uses a folder only SYSTEM and Administrators can write to.
- **Background updates** run as you, never as admin.
- **Storely's own updates** are signed with an Ed25519 key that never leaves the maintainer's PC; the app checks
  the signature before running anything it downloaded.
- **Links**: `storely://` links that do something (like "update all") need a one-time token only Storely's own
  notifications have.

The installers are not Authenticode-signed (that costs money every year), so Windows SmartScreen may say
"unknown publisher" the first time. The SHA256SUMS file on each release, signed with the key above, lets you check
you have the real thing.
