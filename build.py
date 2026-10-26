"""
Step 4 of the manual update process: injects data.json and svgs_min.json
into app_template.html to produce the final, self-contained tool.

Run this after process.py and minify_svg.py have regenerated data.json
and svgs_min.json from your updated drugs.csv / patterns.csv.

Usage:
    python3 build.py

Output:
    index.html  (GitHub Pages serves this file as the site's home page)
"""
import json, os

data = json.load(open("data.json"))
svgs = json.load(open("svgs_min.json"))

template = open("app_template.html", encoding="utf-8").read()
template = template.replace("__STEREO_ACTIVITY_HTML__", open("stereo_activity.html", encoding="utf-8").read())
template = template.replace("__STEREO_ACTIVITY_JS__", open("stereo_activity.js", encoding="utf-8").read())
template = template.replace("__STEREO_JSON__", json.dumps(json.load(open("stereo.json")), separators=(',', ':')))
html = template.replace("__DATA_JSON__", json.dumps(data, separators=(',', ':')))
html = html.replace("__SVGS_JSON__", json.dumps(svgs, separators=(',', ':')))

out_path = "index.html"
with open(out_path, "w", encoding="utf-8") as f:
    f.write(html)

size_mb = os.path.getsize(out_path) / 1e6
print(f"Wrote {out_path} ({size_mb:.2f} MB, {len(data['drugs'])} drugs)")
