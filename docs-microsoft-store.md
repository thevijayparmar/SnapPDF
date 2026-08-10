# SnapPDF — Microsoft Store Submission Guide

Follows the same process used for SnapShrink. SnapPDF is submitted as an
**EXE app** (Microsoft Store has accepted plain .exe/.msi installers
directly since 2021 — no MSIX packaging needed).

---

## PHASE 0 — Already done for you (from the SnapShrink submission)

If you registered as a Microsoft individual developer for SnapShrink,
**you do not need to register again.** One developer account covers every
app you publish. Skip straight to Phase 1.

If you haven't registered yet:
1. Go to **storedeveloper.microsoft.com** (not the old Partner Center link)
2. **Get started for free** → **Individual developer (free)**
3. Sign in with a personal Microsoft account (not a work account)
4. Verify identity: government ID photo + selfie
5. Confirm your public developer/publisher name (e.g. "Vijay Parmar")
6. Wait ~5 minutes, refresh Partner Center until "Apps & Games" appears

---

## PHASE 1 — Prepare the installer + hosting

1. Build the release exe:
   ```
   python installer\build_app.py
   ```
   then compile `installer\SnapPDF.iss` in Inno Setup → produces
   `SnapPDFSetup.exe`.
2. **Host it at a permanent URL** — GitHub Releases is simplest since the
   code is already there:
   - Go to your `snappdf` repo → **Releases** → **Draft a new release**
   - Tag: `v1.01.00` (match your `sppack/__init__.py` version)
   - Upload `SnapPDFSetup.exe` as a release asset
   - Publish the release
   - Your permanent URL will look like:
     `https://github.com/vijayparmar/snappdf/releases/download/v1.01.00/SnapPDFSetup.exe`
3. **Test the URL in a browser** — confirm it downloads the .exe directly,
   not a webpage.
4. Keep this URL handy for Phase 3, Section 4 (Packages).

---

## PHASE 2 — Reserve the app name

1. In Partner Center, click **+ New product**
2. Select **EXE or MSI app**
3. Enter name: **`SnapPDF`**
4. Click **Check availability** → **Reserve product name**
   (You have 3 months to finish the submission after reserving.)

---

## PHASE 3 — Fill in the submission form

### Section 1 — Availability (Pricing & Markets)
- **Pricing:** Free
- **Markets:** All markets (default)
- **Free trial:** N/A — leave unchecked

### Section 2 — Properties
- **Category:** Productivity
- **Subcategory:** Document management / File management (whichever your
  Partner Center dropdown shows — PDF tools fit either)
- **System requirements:**
  - OS: Windows 10 (build 14393) or later
  - RAM: 256 MB minimum (PDF/image libraries are heavier than SnapShrink's)
  - Disk: 150 MB recommended

### Section 3 — Age Ratings
Answer the IARC questionnaire — every question is **No** for SnapPDF
(no violence, no profanity, no user-generated content sharing, no location
data, etc.). Expected result: **3+ / Everyone**.

### Section 4 — Packages
- Click **Add package** → paste your GitHub Releases URL from Phase 1
- Wait for the Store to fetch and validate the file

### Section 5 — Store Listings

Copy-paste the content from the **"Copy-paste form data"** section below
directly into each field.

### Section 6 — Submission options
- **Release date:** As soon as possible
- **Certification notes:**
  > This is a Windows desktop utility app (PDF optimization/merge/convert).
  > No admin privileges required — installs to the user's own folder.
  > Fully offline: no network access, no telemetry, no accounts.
  > Open-source on GitHub: https://github.com/vijayparmar/snappdf

Click **Save** on every section until all six show a green checkmark, then
**Submit for certification**.

---

## PHASE 4 — Certification & publishing

- Certification typically takes up to 3 business days
- You'll get email notifications: submitted → in review → published/rejected
- Once published, the listing appears at `apps.microsoft.com` within
  ~15 minutes of passing certification
- **Updates:** build a new `SnapPDFSetup.exe`, upload it as a new GitHub
  Release, create a new Partner Center submission pointing at the new URL,
  resubmit (usually faster — around 24 hours for updates)

---

## Copy-paste form data (Section 5 — Store Listings)

### App name
```
SnapPDF — Shrink, Merge & Convert PDFs
```

### Short description (up to ~200 characters, shows in search results)
```
Right-click any PDF to shrink, merge, or convert it instantly. Free, open source, fully offline — your files are never uploaded or overwritten.
```

### Full description
```
SnapPDF adds fast, no-nonsense PDF optimization directly to your Windows right-click menu. No app to open, no uploading your documents to a website, no guessing at quality sliders — just right-click any PDF and shrink, merge, or convert it instantly.

HOW IT WORKS

Right-click any PDF file in Windows Explorer and choose from:
• Quick Optimize — one click, uses your saved preset
• Shrink to size — 10 KB up to 5 MB, SnapPDF finds the right settings automatically
• Shrink to % of size — 50% to 95% of the original
• Convert to images — every page exported as JPG, 72 to 300 DPI
• Merge PDFs — combine several files into one, in the order you select them
• Merge & shrink to — combine and hit a size target in one action
• Keep only Text and Vectors — strips every image, keeps text and vector art
• Keep only Text — maximum reduction, rebuilds pages from text alone

Select images instead of PDFs and choose Combine to PDF to turn photos or scans into a single document.

Press Ctrl+Alt+P to instantly optimize whatever PDF is selected in Explorer — no window opens.

WHAT MAKES IT DIFFERENT

• Your originals are always safe — SnapPDF never overwrites the source file, only ever creates a new one
• Fully offline — your documents never leave your computer, no uploads, no servers
• Honest about limits — if a target size genuinely isn't achievable, SnapPDF tells you the closest realistic size instead of failing silently or lying about it
• No account, no login, no subscription
• Installs without admin privileges, straight to your own user folder
• Runs quietly in the system tray — the hotkey is always ready, no app window needed
• Open source — full source code available on GitHub

FULL CONTROL FROM THE APP

Open SnapPDF itself for a live breakdown of where a PDF's storage is going (images, fonts, page content, attachments, metadata, structure), per-category toggles, an image-quality slider, and an estimated output size before you commit to anything.

PERFECT FOR

• Getting a scanned form under a government portal's upload limit
• Shrinking a report so it fits an email attachment limit
• Combining multiple invoices or forms into a single PDF
• Turning a folder of scanned photos into one shareable document
• Producing the smallest possible file when only the text actually matters

PRIVACY

SnapPDF collects zero data. No telemetry, no analytics, no internet connection required, ever.
```

### Release notes
```
Initial release. Shrink to size or percentage, merge PDFs, convert to
images, combine images to PDF, and two aggressive "Keep only" reduction
modes. Ctrl+Alt+P hotkey and full right-click context menu.
```

### Screenshots (up to 9, PNG, 1920×1080 minimum)
Use frames from the FULL.html launch film or record fresh ones showing:
1. Right-click context menu in Explorer (all SnapPDF options visible)
2. Shrink-to-size flyout with a KB target selected
3. The tool window — SINGLE mode analysis panel
4. Merge PDFs in progress / success toast
5. Keep only Text — before/after comparison
6. System tray with SnapPDF running

### App logo
Export the bolt-mark logo used throughout the app/README at 1240×1240 PNG
(minimum 300×300 accepted).

### Keywords (7 max)
```
pdf, compress, shrink, merge, convert, optimize, document
```

### Dev website & support email
- **Website:** `https://github.com/vijayparmar/snappdf`
- **Support email:** your contact email

### Privacy policy
Since SnapPDF doesn't collect data, connect to the internet, or use
accounts, a simple one-line policy is enough — host it as `PRIVACY.md` in
the GitHub repo and link it:
```
SnapPDF does not collect, store, or transmit any personal data. All PDF
processing happens entirely on your device.
```

---

## Quick checklist before you start

- [ ] `SnapPDFSetup.exe` built and tested on a real Windows machine
- [ ] Installer uploaded to a GitHub Release with a stable download URL
- [ ] "SnapPDF" name not already taken on the Store (verify in Phase 2)
- [ ] Screenshots ready (PNG, 1920×1080+)
- [ ] App logo ready (1240×1240 PNG)
- [ ] GitHub repo public (the listing links to it)
- [ ] `PRIVACY.md` added to the repo and linked from the Store form
