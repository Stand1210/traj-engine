"""Artifact fitting: bind data-driven pattern clusters onto declared ontology patterns.

The kernel clusters workflows from data; the ontology declares what a workflow *must*
contain. Neither knows the other's identifiers, so an adaptation step has to line them up.
Doing it by hand per business would make the kernel non-portable, and doing it with labels
would make it supervised. It is done here label-free instead:

  1. Strip the universal actions (present in >= 95% of *all* traces - the agent root, the
     planning step, the summarising step). They carry no routing information.
  2. For each learned pattern cluster, intersect the learned required-step profiles of its
     cells to get the cluster's *core* action set.
  3. Score every declared pattern against that core by Jaccard similarity and bind only
     when the winner is both strong (>= min_score) and unambiguous (margin >= min_margin).

Unbound clusters keep the learned prevalence profile, which is weaker but always available.
The binding is an artifact: it is versioned, inspectable, and refit when the workflow
inventory changes.
"""

UNIVERSAL_PREVALENCE = 0.95


def _jaccard(a, b):
    if not a and not b:
        return 1.0
    u = len(a | b)
    return (len(a & b) / float(u)) if u else 0.0


def pattern_cluster_of(cell):
    if not cell:
        return None
    return cell.split("xp")[-1]


def bind_patterns(art, ontology, min_score=0.60, min_margin=0.20):
    declared = (ontology or {}).get("required_steps") or {}
    if not declared or not art.get("cell"):
        return {}
    univ = set((art.get("global_profile") or {}).get("required") or [])
    dcore = dict((p, set(v) - univ) for p, v in declared.items())
    per = {}
    for cell, ent in art["cell"].items():
        b = pattern_cluster_of(cell)
        if b is None:
            continue
        per.setdefault(b, []).append(set((ent.get("profile") or {}).get("required") or []) - univ)
    binding = {}
    detail = {}
    for b in sorted(per, key=lambda z: str(z)):
        sets = [s for s in per[b] if s]
        if not sets:
            continue
        core = set.intersection(*sets)
        if not core:
            continue
        scored = sorted(((_jaccard(core, d), p) for p, d in dcore.items()),
                        key=lambda t: (-t[0], t[1]))
        best, bp = scored[0]
        second = scored[1][0] if len(scored) > 1 else 0.0
        detail[b] = {"core": sorted(core), "best": bp, "best_score": round(best, 4),
                     "margin": round(best - second, 4),
                     "bound": bool(best >= min_score and (best - second) >= min_margin)}
        if best >= min_score and (best - second) >= min_margin:
            binding[b] = bp
    return binding


def binding_detail(art, ontology, min_score=0.60, min_margin=0.20):
    declared = (ontology or {}).get("required_steps") or {}
    if not declared or not art.get("cell"):
        return {}
    univ = set((art.get("global_profile") or {}).get("required") or [])
    dcore = dict((p, set(v) - univ) for p, v in declared.items())
    per = {}
    for cell, ent in art["cell"].items():
        b = pattern_cluster_of(cell)
        if b is None:
            continue
        per.setdefault(b, []).append(set((ent.get("profile") or {}).get("required") or []) - univ)
    out = {}
    for b in sorted(per, key=lambda z: str(z)):
        sets = [s for s in per[b] if s]
        if not sets:
            continue
        core = set.intersection(*sets)
        if not core:
            continue
        scored = sorted(((_jaccard(core, d), p) for p, d in dcore.items()),
                        key=lambda t: (-t[0], t[1]))
        best, bp = scored[0]
        second = scored[1][0] if len(scored) > 1 else 0.0
        out[b] = {"core": sorted(core), "best": bp, "best_score": round(best, 4),
                  "margin": round(best - second, 4),
                  "bound": bool(best >= min_score and (best - second) >= min_margin)}
    return out


def required_for(art, ontology, binding, cell):
    """Required steps for a cell, plus which of them are *declared* by the ontology.

    Declared steps are a contract: missing one is a violation and needs no statistics.
    Learned steps are a prevalence estimate: missing one is evidence, weighted by how
    universal the step is, and only a large gap is treated as a violation outright.
    """
    ent = (art.get("cell") or {}).get(cell) or {}
    learned = list((ent.get("profile") or {}).get("required") or [])
    if not learned:
        learned = list(((art.get("global_profile") or {}).get("required")) or [])
    b = pattern_cluster_of(cell)
    pid = (binding or {}).get(b)
    if pid is None:
        return {"required": learned, "declared": [], "source": "learned", "pattern": None}
    declared = list(((ontology or {}).get("required_steps") or {}).get(pid) or [])
    return {"required": sorted(set(learned) | set(declared)), "declared": sorted(declared),
            "source": "declared", "pattern": pid}