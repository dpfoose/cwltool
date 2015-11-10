import sys
import urlparse
import json
import re
from aslist import aslist

def findId(doc, frg):
    if isinstance(doc, dict):
        if "id" in doc and doc["id"] == frg:
            return doc
        else:
            for d in doc:
                f = findId(doc[d], frg)
                if f:
                    return f
    if isinstance(doc, list):
        for d in doc:
            f = findId(d, frg)
            if f:
                return f
    return None

def fixType(doc):
    if isinstance(doc, list):
        return [fixType(f) for f in doc]

    if isinstance(doc, basestring):
        if doc not in ("null", "boolean", "int", "long", "float", "double", "string", "File", "record", "enum", "array", "Any") and "#" not in doc:
            return "#" + doc
    return doc

def _draft2toDraft3dev1(doc, loader, baseuri):
    try:
        if isinstance(doc, dict):
            if "import" in doc:
                imp = urlparse.urljoin(baseuri, doc["import"])
                r = loader.fetch(imp)
                if isinstance(r, list):
                    r = {"@graph": r}
                r["id"] = imp
                _, frag = urlparse.urldefrag(imp)
                if frag:
                    frag = "#" + frag
                    r = findId(r, frag)
                return _draft2toDraft3dev1(r, loader, imp)

            if "include" in doc:
                return loader.fetch_text(urlparse.urljoin(baseuri, doc["include"]))

            for t in ("type", "items"):
                if t in doc:
                    doc[t] = fixType(doc[t])

            if "steps" in doc:
                if not isinstance(doc["steps"], list):
                    raise Exception("Value of 'steps' must be a list")
                for i, s in enumerate(doc["steps"]):
                    if "id" not in s:
                        s["id"] = "step%i" % i
                    for inp in s.get("inputs", []):
                        if isinstance(inp.get("source"), list):
                            if "requirements" not in doc:
                                doc["requirements"] = []
                            doc["requirements"].append({"class": "MultipleInputFeatureRequirement"})


            for a in doc:
                doc[a] = _draft2toDraft3dev1(doc[a], loader, baseuri)

        if isinstance(doc, list):
            return [_draft2toDraft3dev1(a, loader, baseuri) for a in doc]

        return doc
    except Exception as e:
        err = json.dumps(doc, indent=4)
        if "id" in doc:
            err = doc["id"]
        elif "name" in doc:
            err = doc["name"]
        raise Exception("Error updating '%s'\n  %s" % (err, e))

def draft2toDraft3dev1(doc, loader, baseuri):
    return (_draft2toDraft3dev1(doc, loader, baseuri), "https://w3id.org/cwl/cwl#draft-3.dev1")

digits = re.compile("\d+")

def updateScript(sc):
    sc = sc.replace("$job", "inputs")
    sc = sc.replace("$tmpdir", "runtime.tmpdir")
    sc = sc.replace("$outdir", "runtime.outdir")
    sc = sc.replace("$self", "self")
    return sc

def _draftDraft3dev1toDev2(doc):
    # Convert expressions
    if isinstance(doc, dict):
        for a in doc:
            ent = doc[a]
            if isinstance(ent, dict) and "engine" in ent:
                if ent["engine"] == "cwl:JsonPointer":
                    sp = ent["script"].split("/")
                    if sp[0] in ("tmpdir", "outdir"):
                        doc[a] = "$(runtime.%s)" % sp[0]
                    else:
                        if not sp[0]:
                            sp.pop(0)
                        sp.pop(0)
                        sp = [str(i) if digits.match(i) else "'"+i+"'"
                              for i in sp]
                        doc[a] = "$(inputs[%s])" % ']['.join(sp)
                else:
                    sc = updateScript(ent["script"])
                    if sc[0] == "{":
                        doc[a] = "$" + sc
                    else:
                        doc[a] = "$(%s)" % sc
            else:
                doc[a] = _draftDraft3dev1toDev2(doc[a])

        if "class" in doc and (doc["class"] in ("CommandLineTool", "Workflow", "ExpressionTool")):
            added = False
            if "requirements" in doc:
                for r in doc["requirements"]:
                    if r["class"] == "ExpressionEngineRequirement":
                        if "engineConfig" in r:
                            doc["requirements"].append({
                                "class":"InlineJavascriptRequirement",
                                "expressionLib": [updateScript(sc) for sc in aslist(r["engineConfig"])]
                            })
                            added = True
                        doc["requirements"] = [rq for rq in doc["requirements"] if rq["class"] != "ExpressionEngineRequirement"]
                        break
            else:
                doc["requirements"] = []
            if not added:
                doc["requirements"].append({"class":"InlineJavascriptRequirement"})

    elif isinstance(doc, list):
        return [_draftDraft3dev1toDev2(a) for a in doc]

    return doc

def draftDraft3dev1toDev2(doc, loader, baseuri):
    return (_draftDraft3dev1toDev2(doc), "https://w3id.org/cwl/cwl#draft-3.dev2")

def update(doc, loader, baseuri):
    updates = {
        "https://w3id.org/cwl/cwl#draft-2": draft2toDraft3dev1,
        "https://w3id.org/cwl/cwl#draft-3.dev1": draftDraft3dev1toDev2,
        "https://w3id.org/cwl/cwl#draft-3.dev2": None
    }

    def identity(doc, loader, baseuri):
        v = doc.get("cwlVersion")
        if v:
            return (doc, loader.expand_url(v, ""))
        else:
            return (doc, "https://w3id.org/cwl/cwl#draft-2")

    nextupdate = identity

    while nextupdate:
        (doc, version) = nextupdate(doc, loader, baseuri)
        if version in updates:
            nextupdate = updates[version]
        else:
            raise Exception("Unrecognized version %s" % version)

    doc["cwlVersion"] = version

    return doc
