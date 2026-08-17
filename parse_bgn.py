#!/usr/bin/env python3
"""Parse U.S. Board on Geographic Names Quarterly Review List PDFs into JSON.

Scope: Review Lists 450-464 (posted February 2023 - July 2026). Every proposal in
these lists opens with a literal "Proposal Information" heading followed by a
label/value block, which is what this parser splits on. Lists 442-449 use an
earlier, materially different layout (compact semicolon-delimited paragraphs with
no case numbers) and are deliberately out of scope rather than parsed loosely.

Output: bgn_raw.json  {lists: [...], proposals: [...]}
Exits non-zero if any in-scope list yields zero proposals.
"""
import fitz, json, re, glob, os, sys

STATES = [
    "Alabama","Alaska","Arizona","Arkansas","California","Colorado","Connecticut",
    "Delaware","Florida","Georgia","Hawaii","Idaho","Illinois","Indiana","Iowa",
    "Kansas","Kentucky","Louisiana","Maine","Maryland","Massachusetts","Michigan",
    "Minnesota","Mississippi","Missouri","Montana","Nebraska","Nevada",
    "New Hampshire","New Jersey","New Mexico","New York","North Carolina",
    "North Dakota","Ohio","Oklahoma","Oregon","Pennsylvania","Rhode Island",
    "South Carolina","South Dakota","Tennessee","Texas","Utah","Vermont",
    "Virginia","Washington","West Virginia","Wisconsin","Wyoming",
    "District of Columbia","Puerto Rico","American Samoa","Guam",
    "Northern Mariana Islands","U.S. Virgin Islands","Virgin Islands"]
STATE_LOOKUP = {s.upper(): s for s in STATES}

LABELS = ["Proposed name","Proposal type","Proponent","Date proposed",
          "BGN case number","Case number","Quarterly Review List",
          "Primary coordinates","Secondary coordinates","Feature class",
          "Feature size","Feature description","Name history",
          "USGS primary topo map","State(s)","County(s)",
          "Local jurisdiction(s)","PLSS","Land ownership",
          "Current official name","Current name","GNIS ID","Feature ID","FID",
          "Elevation","Tribal land","Description",
          "Proposed names","Current official names","GNIS IDs","Submitter"]
SECTIONS = ["Proposal Information","Feature Details","BGN decisions","Other Names",
            "Case Summary","Stakeholder Input","Introduction"]

MIN_LIST, MAX_LIST = 450, 464


def clean(s):
    if s is None:
        return None
    s = (s.replace("’", "'").replace("‘", "'")
          .replace("“", '"').replace("”", '"')
          .replace("ﬁ", "fi").replace("ﬂ", "fl")
          .replace("–", "-").replace("—", "-"))
    return re.sub(r"[ \t]+", " ", s).strip()


def parse_fields(block):
    """Within a proposal block, label line -> following lines are its value."""
    lines = block.split("\n")
    out, i = {}, 0
    while i < len(lines):
        ln = lines[i].strip()
        if ln in LABELS:
            vals, j = [], i + 1
            while j < len(lines):
                nxt = lines[j].strip()
                if nxt in LABELS or nxt in SECTIONS:
                    break
                if nxt and not re.fullmatch(r"\d{1,3}", nxt):   # drop page numbers
                    vals.append(nxt)
                j += 1
            out[ln] = clean(" ".join(vals))
            i = j
        else:
            i += 1
    return out


def section_text(block, name, nexts):
    m = re.search(r"^[ \t]*%s[ \t]*$" % re.escape(name), block, re.M)
    if not m:
        return None
    start, end = m.end(), len(block)
    for n in nexts:
        m2 = re.search(r"^[ \t]*%s[ \t]*$" % re.escape(n), block[start:], re.M)
        if m2:
            end = min(end, start + m2.start())
    body = block[start:end]
    body = re.sub(r"\n[ \t]*\d{1,3}[ \t]*\n", "\n", body)      # page numbers
    body = re.sub(r"[ \t]*\n[ \t]*", " ", body)
    return clean(body) or None


def heading_span(text, pos):
    """Locate the proposal title preceding 'Proposal Information'.

    Returns (title, start_offset) where start_offset is where the heading begins,
    so the previous proposal's block can be truncated before it.
    """
    pre = text[:pos]
    lines = pre.split("\n")
    got, start = [], pos
    consumed = 0
    for ln in reversed(lines):
        consumed += len(ln) + 1
        s = ln.strip()
        if not s or re.fullmatch(r"\d{1,3}", s):
            if got:
                break
            continue
        if s.upper() in STATE_LOOKUP:
            break
        got.insert(0, s)
        start = pos - consumed + 1
        if len(got) >= 4:
            break
    return (clean(" ".join(got)) or None), max(0, start)


FIELDWORDS = re.compile(
    r"\b(Feature description|Name history|Proposal type|Proponent|Proposed name|"
    r"Primary coordinates|Secondary coordinates|Land ownership|GNIS ID|PLSS|"
    r"USGS primary topo|Feature class|Feature size|County\(s\)|State\(s\)|"
    r"Date proposed|BGN case number|Quarterly Review List|Other Names|"
    r"Case Summary|Stakeholder Input)\b")


def title_looks_real(t):
    """Reject titles where the heading grab ran into narrative or field text."""
    if not t:
        return False
    if FIELDWORDS.search(t):
        return False
    if len(t) > 240:
        return False
    if re.search(r"[.;:]\s*$", t):
        return False
    if re.match(r"^(Change|New name|New names)\b", t, re.I):
        return True                      # canonical heading form, allow length
    return len(t) <= 90 and t.count(" ") <= 12


def synth_title(proposed, current, multi=False):
    p = (proposed or "").strip()
    c = (current or "").strip()
    if not p:
        return None
    if multi or "," in p:
        parts = [x.strip() for x in p.split(",") if x.strip()]
        if len(parts) > 3:
            return "New names: %s and %d more" % (", ".join(parts[:3]), len(parts) - 3)
        return "New names: %s" % ", ".join(parts)
    if c and c.lower() not in ("n/a", "na", "none") and c.lower() != p.lower():
        return "Change %s to %s" % (c, p)
    return "New name %s" % p


def state_before(text, pos):
    best = None
    for m in re.finditer(r"^[ \t]*([A-Za-z .'’]+)[ \t]*$", text[:pos], re.M):
        cand = m.group(1).strip()
        if cand.upper() in STATE_LOOKUP:
            best = STATE_LOOKUP[cand.upper()]
    return best


def list_meta(doc, num):
    t = doc[0].get_text()
    d = re.search(r"(?:Date posted|Released)[:\s]*"
                  r"([A-Za-z]+ \d{1,2}, \d{4}|\d{1,2}/\d{1,2}/\d{4})", t)
    names = re.search(r"\((\d+) names\)", t)
    props = re.search(r"Number of proposals[:\s]*(\d+)", t)
    return {
        "list": num,
        "posted": clean(d.group(1)) if d else None,
        "stated_names": int(names.group(1)) if names else None,
        "stated_proposals": int(props.group(1)) if props else None,
    }


def parse_pdf(path):
    num = int(re.search(r"(\d+)", os.path.basename(path)).group(1))
    doc = fitz.open(path)
    meta = list_meta(doc, num)
    text = "\n".join(doc[p].get_text() for p in range(doc.page_count))

    marks = [m.start() for m in
             re.finditer(r"^[ \t]*Proposal Information[ \t]*$", text, re.M)]
    rows = []
    for idx, start in enumerate(marks):
        if idx + 1 < len(marks):
            # end this block where the NEXT proposal's heading begins, so the
            # trailing case summary does not absorb the next title
            _, end = heading_span(text, marks[idx + 1])
            end = max(end, start + 1)
        else:
            end = len(text)
        block = text[start:end]
        title, _ = heading_span(text, start)
        state = state_before(text, start)
        f = parse_fields(block)
        case = f.get("BGN case number") or f.get("Case number")
        rec = {
            "list": num,
            "list_posted": meta["posted"],
            "case_number": case,
            "state": state or f.get("State(s)"),
            "title": title,
            "proposed_name": f.get("Proposed name") or f.get("Proposed names"),
            "multi_name": bool(f.get("Proposed names")),
            "submitter": f.get("Submitter"),
            "proposal_type": f.get("Proposal type"),
            "proponent": f.get("Proponent"),
            "date_proposed": f.get("Date proposed"),
            "coordinates": f.get("Primary coordinates"),
            "feature_class": (f.get("Feature class") or "").lower() or None,
            "feature_size": f.get("Feature size"),
            "feature_description": f.get("Feature description"),
            "name_history": f.get("Name history"),
            "topo_map": f.get("USGS primary topo map"),
            "county": f.get("County(s)"),
            "land_ownership": f.get("Land ownership"),
            "current_name": f.get("Current official name") or f.get("Current name"),
            "gnis_id": f.get("GNIS ID") or f.get("Feature ID") or f.get("FID"),
            "other_names": section_text(block, "Other Names",
                                        ["Case Summary", "Stakeholder Input"]),
            "case_summary": section_text(block, "Case Summary", ["Stakeholder Input"]),
            "stakeholders": section_text(block, "Stakeholder Input", []),
        }
        if rec["coordinates"]:
            m = re.search(r"(-?\d+\.\d+)[,\s]+(-?\d+\.\d+)", rec["coordinates"])
            if m:
                lat, lon = float(m.group(1)), float(m.group(2))
                if -90 <= lat <= 90 and -180 <= lon <= 180:
                    rec["lat"], rec["lon"] = lat, lon
        # strip footnote asterisks the Board uses in some names
        for k in ("proposed_name", "current_name"):
            if rec[k]:
                rec[k] = re.sub(r"\s*\*+\s*$", "", rec[k]).strip()

        # the heading grab sometimes runs into narrative text; when it clearly
        # has, rebuild the title from the structured fields instead of shipping
        # a paragraph as a proposal name
        rec["title_synthesized"] = False
        if not title_looks_real(title):
            alt = synth_title(rec["proposed_name"], rec["current_name"],
                              rec.get("multi_name"))
            if alt:
                title = alt
                rec["title_synthesized"] = True
        rec["title"] = title

        t_low = (title or "").lower()
        ptype = (rec["proposal_type"] or "").lower()
        if t_low.startswith("change") or "change" in ptype:
            rec["kind"] = "change"
        elif "new name" in t_low or "new" in ptype:
            rec["kind"] = "new"
        else:
            rec["kind"] = "other"
        rec["withdrawn"] = "withdrawn" in t_low
        rec["commemorative"] = "commemorat" in ptype
        identifying = (rec["proposed_name"] or rec["case_number"]
                       or "lat" in rec or rec["feature_class"] or rec["case_summary"])
        if not identifying:
            continue                      # a block with no content: parsing artifact
        rows.append(rec)
    return meta, rows


if __name__ == "__main__":
    allrows, metas, failures = [], [], []
    files = sorted(glob.glob("list_*.pdf"),
                   key=lambda x: int(re.search(r"\d+", x).group()))
    for p in files:
        num = int(re.search(r"\d+", p).group())
        if not (MIN_LIST <= num <= MAX_LIST):
            continue
        meta, rows = parse_pdf(p)
        seen, ded = set(), []
        for r in rows:                                   # dedupe on case number
            k = r["case_number"] or (r["title"], r["coordinates"])
            if k in seen:
                continue
            seen.add(k)
            ded.append(r)
        meta["parsed"] = len(ded)
        meta["with_case_number"] = sum(1 for r in ded if r["case_number"])
        meta["with_coords"] = sum(1 for r in ded if "lat" in r)
        meta["with_summary"] = sum(1 for r in ded if r["case_summary"])
        metas.append(meta)
        allrows += ded
        print("%-14s posted=%-20s names=%-4s parsed=%-4d coords=%-4d summary=%d"
              % (p, meta["posted"], meta["stated_names"] or meta["stated_proposals"],
                 meta["parsed"], meta["with_coords"], meta["with_summary"]),
              file=sys.stderr)
        if len(ded) == 0:
            failures.append(p)

    if failures:
        sys.exit("FAIL: no proposals parsed from %s" % ", ".join(failures))
    if len(allrows) < 300:
        sys.exit("FAIL: only %d proposals parsed, expected 300+" % len(allrows))

    json.dump({"lists": metas, "proposals": allrows},
              open("bgn_raw.json", "w"), indent=1)
    print("\nTOTAL %d proposals | %d with coords | %d with case summary | %d states"
          % (len(allrows), sum(1 for r in allrows if "lat" in r),
             sum(1 for r in allrows if r["case_summary"]),
             len({r["state"] for r in allrows if r["state"]})), file=sys.stderr)
