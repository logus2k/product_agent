"""Product stage — turn requirements into a product/experience definition.

Reads the Analyst's requirements package, asks the active model to design the PRODUCT (personas & roles,
primary journeys, information architecture = surfaces + screen/navigation map, landing experience), and
writes `product/product_spec.json` + `product/product_brief.md` into the repo, committed via reqoach.

Generic by construction: the only input is the requirements, so it works for ANY app the FACTORY builds.
The spec is the contract the Architect and the Builder-frontend consume downstream.
"""

from __future__ import annotations

import json
import os
import time
import urllib.request

REPOS_ROOT = os.environ.get("PROJECT_REPOS_ROOT", "/app/project-repos")
REQOACH_URL = os.environ.get("REQOACH_URL", "http://localhost:7802").rstrip("/")
MODEL_URL = os.environ.get("PRODUCT_LLM_URL", "http://127.0.0.1:8500").rstrip("/")


def _resolve_model() -> str:
    """Use whatever CHAT model is ACTIVE on the server (never pin an id). PRODUCT_LLM_MODEL overrides."""
    override = os.environ.get("PRODUCT_LLM_MODEL")
    if override:
        return override
    try:
        data = json.load(urllib.request.urlopen(f"{MODEL_URL}/v1/models", timeout=5)).get("data", [])
        cands = []
        for m in data:
            mid = m.get("id", "")
            if any(x in mid.lower() for x in ("bge", "embed", "rerank")):
                continue
            loaded = ((m.get("status") or {}).get("value") == "loaded")
            nparams = ((m.get("meta") or {}).get("n_params")) or 0
            cands.append((loaded, nparams, mid))
        if cands:
            cands.sort(key=lambda t: (t[0], t[1]), reverse=True)
            return cands[0][2]
    except Exception:
        pass
    return "gemma-4-12b"


def _load_requirements(pid: str) -> dict:
    """Read the Analyst's requirements package for the project."""
    p = os.path.join(REPOS_ROOT, pid, "requirements", "package.json")
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def _problem_text(ps) -> str:
    """Extract the human-readable problem statement (the authoritative 'what this system is') from the
    Analyst's problem_statement, whether it's a plain string or the nested {statement:{purpose:{value}}}
    structure. This is what the product framing must stay faithful to."""
    if not ps:
        return ""
    if isinstance(ps, str):
        return ps
    st = ps.get("statement") if isinstance(ps, dict) else None
    if isinstance(st, dict):
        parts = []
        for key in ("purpose", "scope", "context", "problem"):
            v = st.get(key)
            val = v.get("value") if isinstance(v, dict) else v
            if val:
                parts.append(f"{key}: {val}")
        if parts:
            return "\n".join(parts)
    return json.dumps(ps)[:1200]


def _requirements_digest(pkg: dict) -> str:
    """The FULL requirement set as compact text for the model — problem statement + every requirement
    (id · type · text). No blind truncation: all requirements are sent (they are one line each)."""
    lines = []
    ps = pkg.get("problem_statement")
    ptxt = _problem_text(ps)
    if ptxt:
        lines.append("PROBLEM STATEMENT (the authoritative description of what this system is):\n" + ptxt)
    lines.append("\nREQUIREMENTS:")
    for r in pkg.get("requirements", []) or []:
        rid = r.get("req_id", "?")
        typ = (r.get("type") or (r.get("classes") or ["?"])[0])
        txt = r.get("text", "")
        lines.append(f"- {rid} [{typ}] {txt}")
    gl = pkg.get("glossary")
    if isinstance(gl, dict) and gl:
        terms = list(gl.items())[:40]
        lines.append("\nGLOSSARY:")
        for k, v in terms:
            d = v.get("definition") if isinstance(v, dict) else v
            lines.append(f"- {k}: {d}")
    return "\n".join(lines)


_SCHEMA_HINT = """Return STRICT JSON only (no markdown, no prose) with EXACTLY these top-level keys:
{
  "product_name": "short product name",
  "one_liner": "one sentence: what it is and for whom",
  "personas": [
    {"id":"owner","name":"Restaurant Owner","role":"admin","goals":["..."],"is_primary":false}
  ],
  "surfaces": [
    {"id":"public","name":"Public Storefront","audience":"public","personas":["diner"],
     "purpose":"what this surface is for"},
    {"id":"admin","name":"Owner Dashboard","audience":"authenticated","personas":["owner"],
     "purpose":"..."}
  ],
  "screens": [
    {"id":"home","title":"...","surface":"public","audience":"public","primary_persona":"diner",
     "is_landing":true,"purpose":"what the user does here","key_actions":["..."],
     "requirements":["REQ-0001"]}
  ],
  "journeys": [
    {"id":"book_table","persona":"diner","name":"Book a table",
     "steps":["land on public menu","...","confirmation"],"entry_screen":"home"}
  ],
  "navigation": {
    "public": [{"label":"Menu","screen":"home"}],
    "admin": [{"label":"Dashboard","screen":"admin_home"}]
  },
  "landing_screen": "home"
}
Rules: identify the DISTINCT user roles (e.g. an admin/owner vs an end customer) and SEPARATE their
surfaces (public vs authenticated). The landing screen is the PRIMARY user's entry (usually the public
one), NOT an index of internal modules. Every screen must map to >=1 requirement id. Frame screens as
USER TASKS, not database tables. Keep it faithful to the requirements — invent no features.

FAITHFULNESS OF THE WORDING: `product_name` and `one_liner` must plainly restate what THIS system is,
grounded in the PROBLEM STATEMENT above. Describe it in the requirements' own terms. Do NOT add
positioning or marketing framing that the requirements do not state — for example do NOT call it a
"SaaS platform", "multi-tenant", "AI-powered", "enterprise", "cutting-edge", "seamless", or "end-to-end"
unless those exact concepts appear in the requirements. If the requirements say "AI-ASSISTED", write
"AI-assisted", not "AI-powered". A reader comparing your one_liner to the problem statement must find no
claim that isn't supported there."""


def _generate_spec(digest: str, log=print) -> dict:
    """Ask the active model to design the product from the requirements; return the parsed spec dict."""
    prompt = ("You are a senior PRODUCT DESIGNER. Given the requirements of an application, define the "
              "PRODUCT a real user would use: the distinct user roles, the primary user journeys, and the "
              "information architecture — which surfaces are public vs authenticated, the screen map, the "
              "navigation, and the landing experience. Design the EXPERIENCE that satisfies the "
              "requirements; do not mirror the system's internal modules.\n\n"
              + _SCHEMA_HINT + "\n\n=== REQUIREMENTS ===\n" + digest)
    body = json.dumps({"model": _resolve_model(),
                       "messages": [{"role": "user", "content": prompt}],
                       "temperature": 0.4, "max_tokens": 6144,
                       "response_format": {"type": "json_object"},
                       "chat_template_kwargs": {"enable_thinking": False}}).encode()
    t0 = time.time()
    req = urllib.request.Request(f"{MODEL_URL}/v1/chat/completions", data=body,
                                 headers={"Content-Type": "application/json"}, method="POST")
    out = json.load(urllib.request.urlopen(req, timeout=240))["choices"][0]["message"]["content"]
    log(f"model returned {len(out)} chars in {round(time.time()-t0,1)}s")
    spec = _parse_json(out)
    return spec


def _parse_json(text: str) -> dict:
    """Robustly parse the model's JSON: strip a think block / markdown fence, else slice first { .. last }."""
    if "</think>" in text:
        text = text.rsplit("</think>", 1)[1]
    if "```" in text:
        parts = text.split("```")
        text = parts[1] if len(parts) > 1 else text
        if text.lower().lstrip().startswith("json"):
            text = text.lstrip()[4:]
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        a, b = text.find("{"), text.rfind("}")
        if a >= 0 and b > a:
            return json.loads(text[a:b + 1])
        raise


def _validate(spec: dict) -> list[str]:
    """Return a list of problems; empty means the spec has the shape the Architect/Builder need."""
    problems = []
    for k in ("personas", "surfaces", "screens", "landing_screen"):
        if not spec.get(k):
            problems.append(f"missing/empty '{k}'")
    screens = spec.get("screens") or []
    ids = {s.get("id") for s in screens}
    if spec.get("landing_screen") and spec["landing_screen"] not in ids:
        problems.append("landing_screen is not one of the screens")
    if screens and not any((s.get("audience") == "public") for s in screens):
        problems.append("no public screen (every app needs an entry a first-time user can reach)")
    if len(spec.get("personas") or []) < 1:
        problems.append("no personas")
    return problems


def _brief_md(spec: dict) -> str:
    """A human-readable product brief for the UI / reviewers."""
    L = [f"# {spec.get('product_name', 'Product')}", "", spec.get("one_liner", ""), "", "## Users"]
    for p in spec.get("personas", []):
        star = " (primary)" if p.get("is_primary") else ""
        L.append(f"- **{p.get('name', p.get('id'))}**{star} — {p.get('role', '')}: {', '.join(p.get('goals', []))}")
    L += ["", "## Surfaces"]
    for s in spec.get("surfaces", []):
        L.append(f"- **{s.get('name')}** ({s.get('audience')}) — {s.get('purpose', '')}")
    L += ["", "## Screens"]
    for s in spec.get("screens", []):
        land = " · LANDING" if s.get("is_landing") else ""
        L.append(f"- **{s.get('title')}** [{s.get('surface')}/{s.get('audience')}]{land} — "
                 f"{s.get('purpose', '')}  \n  actions: {', '.join(s.get('key_actions', []))}  \n  "
                 f"requirements: {', '.join(s.get('requirements', []))}")
    L += ["", "## Journeys"]
    for j in spec.get("journeys", []):
        L.append(f"- **{j.get('name')}** ({j.get('persona')}): " + " → ".join(j.get("steps", [])))
    return "\n".join(L) + "\n"


def publish(pid: str, message: str, log=print) -> dict:
    """Commit the product area via reqoach (single-owner area, authored as the Product Agent)."""
    try:
        body = json.dumps({"area": "product", "agent": "product", "message": message}).encode()
        req = urllib.request.Request(f"{REQOACH_URL}/repos/{pid}/commit", data=body,
                                     headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r)
    except Exception as e:  # noqa: BLE001 — a commit failure must not fail the run
        log(f"reqoach commit skipped: {type(e).__name__}")
        return {}


def design(pid: str, log=print) -> dict:
    """Design the product from the project's requirements; write product_spec.json + product_brief.md,
    commit, and return a summary manifest. Retries generation once if the first spec is malformed."""
    pkg = _load_requirements(pid)
    digest = _requirements_digest(pkg)
    log(f"loaded {len(pkg.get('requirements', []))} requirements; designing the product…")

    spec, problems = None, ["(not generated)"]
    for attempt in (1, 2):
        try:
            spec = _generate_spec(digest, log)
        except Exception as e:  # noqa: BLE001
            log(f"generation attempt {attempt} failed: {type(e).__name__}: {str(e)[:120]}")
            continue
        problems = _validate(spec)
        if not problems:
            break
        log(f"attempt {attempt} spec has issues: {problems}; {'retrying' if attempt == 1 else 'keeping best effort'}")
    if spec is None:
        raise RuntimeError("product generation failed (model unreachable or unparseable)")

    # The product NAME is not the model's to invent — it IS the project's name. Override deterministically
    # with the Analyst manifest's project_name so the delivered app is branded as the actual project.
    proj_name = (pkg.get("manifest") or {}).get("project_name") or (pkg.get("manifest") or {}).get("name")
    if proj_name:
        spec["product_name"] = proj_name

    outdir = os.path.join(REPOS_ROOT, pid, "product")
    os.makedirs(outdir, exist_ok=True)
    with open(os.path.join(outdir, "product_spec.json"), "w", encoding="utf-8") as f:
        json.dump(spec, f, indent=2)
    with open(os.path.join(outdir, "product_brief.md"), "w", encoding="utf-8") as f:
        f.write(_brief_md(spec))
    commit = publish(pid, "Product: product/experience definition from requirements", log)

    personas = spec.get("personas", [])
    surfaces = spec.get("surfaces", [])
    screens = spec.get("screens", [])
    manifest = {"project_id": pid, "product_name": spec.get("product_name"),
                "one_liner": spec.get("one_liner"),
                "personas": len(personas), "surfaces": len(surfaces), "screens": len(screens),
                "journeys": len(spec.get("journeys", [])),
                "landing_screen": spec.get("landing_screen"),
                "surface_audiences": {s.get("id"): s.get("audience") for s in surfaces},
                "valid": not problems, "problems": problems, "repo": commit}
    log(f"product designed: {len(personas)} persona(s), {len(surfaces)} surface(s), {len(screens)} screen(s); "
        f"landing={spec.get('landing_screen')}; valid={not problems}")
    return manifest
