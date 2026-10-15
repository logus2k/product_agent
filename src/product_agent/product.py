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


class RequirementsNotPublished(RuntimeError):
    """The Analyst's package has not been snapshotted into the project repo yet.

    Raised instead of letting a bare FileNotFoundError escape: the missing file is a
    STEP not taken, not a broken install, and the raw path tells the reader nothing
    about what to do. The package reaches `requirements/` when the set is signed off
    (reqoach's publish:requirements), so the fix is upstream of this stage.
    """


def _load_requirements(pid: str) -> dict:
    """Read the Analyst's requirements package for the project."""
    p = os.path.join(REPOS_ROOT, pid, "requirements", "package.json")
    if not os.path.isfile(p):
        raise RequirementsNotPublished(
            "the requirements package has not been published to this project's repository yet "
            f"(expected {p}). The Analyst writes it there when the requirement set is signed off: "
            "close the open coverage gaps, approve the release (draft -> validated), and the "
            "package is published automatically. To publish an already-released set, POST "
            f"/repos/{pid}/publish:requirements on reqoach."
        )
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        raise RequirementsNotPublished(
            f"the requirements package at {p} is not valid JSON ({e}); re-publish it from reqoach"
        ) from e


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
     "is_landing":true,"purpose":"what the user does here","requirements":["REQ-0001"],
     "actions":[
       {"id":"browse_menu","label":"Browse the menu","kind":"list","entity":"menu_item"},
       {"id":"start_booking","label":"Book a table","kind":"create","entity":"reservation"}
     ]}
  ],
  "journeys": [
    {"id":"book_table","persona":"diner","name":"Book a table","entry_screen":"home",
     "creates":["reservation"],"state":["reservation_id"],
     "flow":[
       {"screen":"home","action":"start_booking"},
       {"screen":"booking_form","action":"submit_reservation"},
       {"screen":"confirmation","action":"view_confirmation"}
     ]}
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

INTERACTION DESIGN (this is what makes the product buildable, not just a picture). For every screen list
its concrete `actions` — each is one thing a user DOES on that screen:
- `kind` is EXACTLY one of: create | list | view | update | delete | search | navigate. (These are the
  only allowed values — they map to how the system realizes the action. Use `create` for anything that
  ADDS a record, `update`/`delete` for changing/removing one, `list`/`view`/`search` for reading, and
  `navigate` for moving to another screen with no data change.)
- `entity` is the data thing the action reads or writes (a noun from the requirements' domain, e.g.
  reservation, order, product). `navigate` actions may omit it.
For every `journey`, give the ordered `flow` as (screen, action) steps that reference REAL screen ids and
REAL action ids on those screens; list in `state` the identifiers carried between steps (e.g. the id of a
record made in an earlier step and used later); and list in `creates` every entity the journey MUST bring
into being. HARD RULE: if a journey `creates` an entity, its `flow` MUST include at least one step whose
action `kind` is `create` for that entity, on a screen the user can actually reach from the entry screen —
otherwise the journey can never complete. A create action is what turns a page into a working feature; do
not describe a purchase/booking/submission journey whose create step has no create action.

FAITHFULNESS OF THE WORDING: `product_name` and `one_liner` must plainly restate what THIS system is,
grounded in the PROBLEM STATEMENT above. Describe it in the requirements' own terms. Do NOT add
positioning or marketing framing that the requirements do not state — for example do NOT call it a
"SaaS platform", "multi-tenant", "AI-powered", "enterprise", "cutting-edge", "seamless", or "end-to-end"
unless those exact concepts appear in the requirements. If the requirements say "AI-ASSISTED", write
"AI-assisted", not "AI-powered". A reader comparing your one_liner to the problem statement must find no
claim that isn't supported there."""


def _generate_spec(digest: str, log=print) -> dict:
    """Ask the active model to design the product from the requirements; return the parsed spec dict."""
    prompt = ("You are a senior PRODUCT & UX DESIGNER. Given the requirements of an application, define the "
              "PRODUCT a real user would use AND how they move through it: the distinct user roles, the "
              "information architecture (which surfaces are public vs authenticated, the screen map, the "
              "navigation, the landing experience), and — crucially — the INTERACTION DESIGN: the concrete "
              "actions on each screen and the step-by-step journeys that connect them, so every task a user "
              "must accomplish has a real, reachable control. Design the EXPERIENCE that satisfies the "
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


#: The only realization-kinds an action may declare — they map onto how the system implements the action
#: (create/list/view/update/delete/search echo the CRUD verbs downstream; navigate is a pure screen move).
_ACTION_KINDS = {"create", "list", "view", "update", "delete", "search", "navigate"}


def _normalize_interaction(spec: dict) -> None:
    """Keep the structured interaction design and the legacy free-text fields in sync, IN PLACE. The
    structured `actions`/`flow` are the source of truth (the Architect binds operations to them, the Builder
    wires controls to them); the older `key_actions`/`steps` are back-filled from them so existing readers
    that expect prose keep working. Additive and defensive — never raises on a partial spec."""
    for s in (spec.get("screens") or []):
        acts = s.get("actions") or []
        if acts and not s.get("key_actions"):
            s["key_actions"] = [a.get("label") or a.get("id") for a in acts if isinstance(a, dict)]
    for j in (spec.get("journeys") or []):
        flow = j.get("flow") or []
        if flow and not j.get("steps"):
            j["steps"] = [f"{f.get('screen')}: {f.get('action')}" for f in flow if isinstance(f, dict)]


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

    # INTERACTION-DESIGN invariants — this is what makes journeys buildable rather than improvised.
    actions_by_screen = {s.get("id"): {a.get("id"): a for a in (s.get("actions") or []) if isinstance(a, dict)}
                         for s in screens}
    all_actions = [a for m in actions_by_screen.values() for a in m.values()]
    if screens and not all_actions:
        problems.append("no screen declares any `actions` (the interaction design is missing)")
    for a in all_actions:
        if a.get("kind") not in _ACTION_KINDS:
            problems.append(f"action '{a.get('id')}' has invalid kind '{a.get('kind')}' "
                            f"(allowed: {sorted(_ACTION_KINDS)})")
    for j in (spec.get("journeys") or []):
        jid = j.get("id")
        flow = j.get("flow") or []
        for f in flow:
            sc, ac = (f.get("screen") if isinstance(f, dict) else None), (f.get("action") if isinstance(f, dict) else None)
            if sc not in actions_by_screen:
                problems.append(f"journey '{jid}' step references unknown screen '{sc}'")
            elif ac not in actions_by_screen.get(sc, {}):
                problems.append(f"journey '{jid}' step references unknown action '{ac}' on screen '{sc}'")
        # a journey that must CREATE an entity needs a reachable create action for it
        for ent in (j.get("creates") or []):
            has_create = any((actions_by_screen.get(f.get("screen"), {}).get(f.get("action"), {}) or {}).get("kind") == "create"
                             for f in flow if isinstance(f, dict))
            if not has_create:
                problems.append(f"journey '{jid}' claims to create '{ent}' but its flow has no create action")
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
        _normalize_interaction(spec)          # keep structured actions/flow and legacy prose fields in sync
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
