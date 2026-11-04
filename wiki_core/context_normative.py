"""Authority for explicitly declared, whole inherited normative inputs."""
from wiki_core.context_policy import PolicyError, historical_policy, safe_path, within


def normative_allowed(policy, context, ref):
    if getattr(policy, 'format_version', None):
        raise PolicyError('v2 normative checks require the versioned v2 interface')
    ref = safe_path(ref)
    if any(within(ref, scope) for scope in policy.effective[context]['deny']['read']):
        return False
    return any(ref in c[key] for c in policy.lineage(context)
               for key in ('instructions', 'skills', 'templates'))


def normative_history(policy, context, ref, revision):
    """Check current authority and approved ancestry before historical bodies."""
    if not normative_allowed(policy, context, ref):
        return False
    try:
        prior = historical_policy(policy, revision)
        return normative_allowed(prior, context, ref) and prior.owner_of(ref) == policy.owner_of(ref)
    except (PolicyError, KeyError, ValueError):
        return False
