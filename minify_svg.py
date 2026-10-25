import re, json, hashlib

def round_path_numbers(d):
    def repl(m):
        return f"{float(m.group(0)):.1f}"
    return re.sub(r'-?\d+\.\d+', repl, d)

def minify_svg(svg, size=None):
    # drop xml prolog, comments, rdkit namespace, baseProfile, xml:space
    svg = re.sub(r"<\?xml.*?\?>", "", svg)
    svg = re.sub(r"<!--.*?-->", "", svg, flags=re.S)
    svg = svg.replace("xmlns:rdkit='http://www.rdkit.org/xml'", "")
    svg = re.sub(r"baseProfile='full'", "", svg)
    svg = re.sub(r"xml:space='preserve'", "", svg)
    svg = re.sub(r"version='1.1'\s*", "", svg)
    # strip RDKit's verbose descriptive class attrs (e.g. class='bond-0 atom-0 atom-1') — unused by us
    svg = re.sub(r"\s*class='[^']*'", "", svg)
    # collapse whitespace/newlines between tags
    svg = re.sub(r">\s+<", "><", svg)
    svg = re.sub(r"\s{2,}", " ", svg)

    # extract style="..." attributes, dedupe into classes
    styles = {}
    def style_repl(m):
        s = m.group(1)
        # normalize spacing
        s = re.sub(r'\s*:\s*', ':', s)
        s = re.sub(r'\s*;\s*', ';', s).strip(';')
        h = hashlib.md5(s.encode()).hexdigest()[:8]
        cls = f"s{h}"
        styles[cls] = s
        return f'class="{cls}"'
    svg = re.sub(r"style='([^']*)'", style_repl, svg)

    # reduce numeric precision in path d attributes and coordinate lists
    def path_repl(m):
        return "d='" + round_path_numbers(m.group(1)) + "'"
    svg = re.sub(r"d='([^']*)'", path_repl, svg)

    # reduce precision in x=,y=,cx=,cy=,width=,height= etc (single float attrs)
    def num_attr_repl(m):
        return f"{m.group(1)}='{float(m.group(2)):.1f}'"
    svg = re.sub(r"(x|y|cx|cy|rx|ry)='(-?\d+\.\d+)'", num_attr_repl, svg)

    style_block = "<style>" + "".join(f".{c}{{{s}}}" for c, s in styles.items()) + "</style>"
    svg = svg.replace("<!-- END OF HEADER -->", "")
    # insert style block right after the opening <svg ...> tag
    svg = re.sub(r"(<svg[^>]*>)", r"\1" + style_block, svg, count=1)
    return svg

if __name__ == "__main__":
    svgs = json.load(open("svgs.json"))
    out = {}
    total_before = sum(len(v) for v in svgs.values())
    for k, v in svgs.items():
        out[k] = minify_svg(v)
    total_after = sum(len(v) for v in out.values())
    print(f"before: {total_before} bytes, after: {total_after} bytes, ratio: {total_after/total_before:.2%}")
    json.dump(out, open("svgs_min.json", "w"))
