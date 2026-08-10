# Security

## Why does Windows SmartScreen warn about SnapPDF?

When you first run `SnapPDFSetup.exe`, Windows may show:

> **Windows protected your PC**
> Microsoft Defender SmartScreen prevented an unrecognized app from starting.

This is **expected** and not a sign of a problem. SmartScreen's reputation
system is built around code-signing certificates, which cost several hundred
dollars a year to maintain. SnapPDF is a free, independently-published,
open-source tool — the same warning appears for thousands of legitimate
small projects that haven't paid for a certificate. It disappears once
enough people have run the app and reported it as safe (reputation grows
over time), or immediately if you code-sign your own build.

**To proceed:** click **More info → Run anyway**.

## How to verify the app yourself, instead of trusting a warning

You don't have to take our word for it. Because SnapPDF is fully open
source, you have three ways to check exactly what you're installing:

1. **Read the source.** Every line of the optimization engine, GUI, and
   installer is in this repository — nothing is hidden or obfuscated.
2. **Build it yourself.** `python installer/build_app.py` produces the
   exact same `SnapPDF.exe` from source, on your own machine, so you know
   the release binary matches the code you can read.
3. **Scan the release binary.** Upload `SnapPDFSetup.exe` to
   [VirusTotal](https://www.virustotal.com/) before running it — this
   checks it against 70+ antivirus engines at once.

## What SnapPDF does and does not do

- **Fully offline.** SnapPDF never makes a network request. There is no
  telemetry, no analytics, no "phone home," no update checker calling out
  on its own.
- **No account, no license key, no server.** Nothing about how SnapPDF
  runs depends on anything outside your machine.
- **Originals are never modified.** Every action writes a new file;
  the source PDF you right-clicked is never opened for writing.
- **No admin rights required.** The installer places SnapPDF in your own
  user folder (`%LocalAppData%\Programs\SnapPDF`), not `Program Files` —
  this is also *why* it can't require admin: a per-user folder doesn't
  need elevated permission to write to.

## Reporting a vulnerability

If you find a security issue (not a general bug — use
[Issues](../../issues) for those), please open a private report via
GitHub's **Security → Report a vulnerability** tab on this repository,
or reach out via [LinkedIn](https://www.linkedin.com/in/thevijayparmar/).
Please don't open a public issue for anything that could be actively
exploited before a fix ships.
