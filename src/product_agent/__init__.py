"""Product Agent — the FACTORY stage between Analysis and Architecture.

It turns the Analyst's REQUIREMENTS (the "what") into a PRODUCT DEFINITION (the "experience that
satisfies them"): personas & roles, primary user journeys, the information architecture (surfaces —
public vs authenticated — and the screen/navigation map), and the landing experience. This artifact
then constrains the Architect (which must design services/entities/auth to support the journeys and
roles) and drives the Builder's frontend (pages generated from the SCREEN MAP, not from service names).

Without it, the UI falls out of the technical decomposition — every project ships as an index of the
modules that were built, with no coherent user. Deliberately generic: it reads only the requirements,
so it generalises to ANY app the FACTORY builds.
"""

__version__ = "0.1.0"
