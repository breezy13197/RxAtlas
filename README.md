# Rx Substructure Atlas

A free practice website for core medicinal chemistry skills. Students look at the structures of about 400 real drugs and practice:

- naming heterocycles and functional groups
- deciding whether a group is acidic, basic, or neutral
- counting hydrogen-bond donors/acceptors and stereocenters
- applying Lipinski's Rule of Five
- primary / secondary / tertiary amines and alcohols
- picking the most basic nitrogen
- finding a group by clicking on it

The whole site is a single file, `index.html`. It needs no server, no logins, and no internet connection once it has loaded.

---

## What students get

| Tab | What it does |
|---|---|
| **Browse** | Every drug in the set. Click a group on the left to see every drug that contains it, highlighted. |
| **Learn** | Flashcards: name the highlighted group, flip, and rate yourself. Cards you're still learning come back more often. |
| **Quiz Me** | Practice questions with an explanation after every answer. Students can mark an answer as a guess, review questions they missed, or build a 5–25 question quiz set. |
| **My Progress** | A dashboard showing mastery by question type, the groups they struggle with (with a one-click "Practice these" button), a 14-day activity chart, and a list of questions to review. |
| **Question Bank** | Students save questions here and download them as a Word document. |

### Where student progress is saved (and why it matters)

Progress is saved **only in the student's own web browser** (a browser feature called "local storage"). Nothing is sent to you or anyone else, so there are no accounts or student-privacy concerns. The trade-offs:

- Progress is tied to **one browser on one device**. A student who switches from a laptop to a phone starts fresh on the phone.
- **Clearing browser history** or using a **private/incognito window** erases it.
- Students can protect themselves with **My Progress → Download backup**, and load it on any device with **Restore from backup**.
- If you want proof of practice, students can use **My Progress → Print / save as PDF** and upload the PDF to a Brightspace assignment.

---

## Putting it online with GitHub Pages (one-time setup)

GitHub Pages hosts the site for free. Every time you update the files on GitHub, students automatically see the new version the next time they open or refresh the page.

1. **Make the repository public.** On GitHub, open the repository → **Settings** → scroll to the bottom (**Danger Zone**) → **Change visibility** → **Make public**. *Why:* free GitHub accounts can only use Pages for public repositories.
2. **Turn on Pages.** **Settings** → **Pages** (left sidebar). Under **Build and deployment**, set **Source** to *Deploy from a branch*, choose the **main** branch and the **/ (root)** folder, then click **Save**.
3. **Wait a minute or two**, then refresh that page. GitHub shows your site's address, which will be:

   **https://breezy13197.github.io/RxAtlas/**

That's it. The small empty file `.nojekyll` in this repository tells GitHub to publish the files exactly as they are, without running them through its blog-building tool. That makes publishing faster and avoids surprises.

### Sharing it in Brightspace

Add the address above as a **link** (in Content: *Upload/Create → Create a Link*), and tick **Open as External Resource** so it opens in its own tab.

Please **don't** upload the `index.html` file itself or embed the page inside a Brightspace frame:

- An **uploaded copy never updates**. Students would be stuck on the old version.
- Browsers (especially Safari) often block or separate saved data for pages shown inside another site's frame, so students' **progress could seem to disappear**.

---

## Updating the drugs or groups

You only need this when you change the drug list or the group definitions. Changes to the app's look or behavior only need step 4.

### One-time: install the tools

You need [Python 3](https://www.python.org/downloads/) and RDKit (the chemistry toolkit that reads structures). Open a terminal (Mac: *Terminal*; Windows: *Command Prompt*) in this folder and run:

```
pip install -r requirements.txt
```

This reads `requirements.txt` and installs RDKit.

### Every update

1. **Edit the spreadsheets.** Open `drugs.csv` or `patterns.csv` in Excel (or Google Sheets) and save as CSV.
   - `drugs.csv` columns: `generic_name`, `brand_example`, `drug_class`, `smiles` (the structure written as a SMILES string; PubChem lists one for every drug).
   - `patterns.csv` columns: `label`, `category` (exactly `Heterocycle` or `Functional group`), `smarts` (the substructure pattern), `acid_base` (exactly `acidic`, `basic`, or `neutral`), `pka_note`.
2. **Process the structures.** Run each of these commands in the terminal, one at a time:
   ```
   python3 process.py
   python3 minify_svg.py
   ```
   `process.py` draws each drug and finds every group in it (creating `data.json` and `svgs.json`). `minify_svg.py` shrinks the drawings so the page loads faster (creating `svgs_min.json`).
3. **Check for problems.**
   ```
   python3 validate.py
   ```
   This catches mistakes that wouldn't otherwise show up, such as a typo in a category name, a pattern that matches no drugs, a group that can never be quizzed, or a drug removed by accident (which would erase students' saved progress for that drug). **Errors** must be fixed. **Warnings** are worth reading but won't break anything.
4. **Build the page.**
   ```
   python3 build.py
   ```
   This combines everything into `index.html`.
5. **Publish.** Upload the changed files to GitHub (or commit and push them). Students see the update within a few minutes.

> **Tip:** don't rename a drug in `drugs.csv` unless you need to. Students' saved progress and question banks refer to drugs by name, so a renamed drug looks like a deleted one, and their history for it is dropped.

---

## What each file is

| File | Purpose |
|---|---|
| `index.html` | **The finished website.** This is what students use. Built automatically; don't edit it by hand. |
| `app_template.html` | The app's design and behavior. Edit this to change how the site looks or works, then run `build.py`. |
| `drugs.csv` | The list of drugs and their structures. |
| `patterns.csv` | The list of groups and how to recognize them. |
| `process.py` | Step 2a: analyzes every drug with RDKit. |
| `minify_svg.py` | Step 2b: shrinks the structure drawings. |
| `validate.py` | Step 3: checks the data for problems. |
| `build.py` | Step 4: produces `index.html`. |
| `data.json`, `svgs.json`, `svgs_min.json` | Intermediate files made by steps 2a–2b. |
| `requirements.txt` | Lists the Python tools to install (RDKit). |
| `.nojekyll` | Tells GitHub Pages to publish files as-is. |

### How some answers are worked out

- **H-bond donors:** each N, O, or S atom with at least one H attached.
- **H-bond acceptors:** O and S atoms (except the OH of acids), nitrogens not attached to a C=O-type group, aromatic N without an H, and F. This can run 1–2 higher than the simpler "count every N and O" rule. Students see this definition with every question.
- **Stereocenters:** tetrahedral stereocenters only, including unspecified ones. E/Z double bonds aren't counted.
- **Most basic nitrogen:** a rule-of-thumb ranking (aliphatic amine > aniline > pyridine-type > amide, and so on), not a calculated pKa. Questions are only generated when one nitrogen is clearly the most basic.
