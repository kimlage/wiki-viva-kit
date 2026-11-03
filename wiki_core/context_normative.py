"""Authority for explicitly declared, whole inherited normative inputs."""
import subprocess
import re
from wiki_core.context_policy import PolicyError, load_policy, safe_path, within


def normative_allowed(policy, context, ref):
    ref = safe_path(ref)
    if any(within(ref, scope) for scope in policy.effective[context]['deny']['read']):
        return False
    return any(ref in c[key] for c in policy.lineage(context)
               for key in ('instructions', 'skills', 'templates'))


def normative_history(policy, context, ref, revision):
    """Check current authority and approved ancestry before historical bodies."""
    if not isinstance(revision, str) or not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', revision):
        return False
    if not normative_allowed(policy, context, ref):
        return False
    root, _, manifest = policy._binding
    if subprocess.run(['git', '-C', str(root), 'merge-base', '--is-ancestor', revision,
                       policy.policy_revision], stdout=subprocess.DEVNULL,
                      stderr=subprocess.DEVNULL).returncode:
        return False
    try:
        prior = load_policy(root, revision, manifest, trusted_ref=revision)
        return normative_allowed(prior, context, ref) and prior.owner_of(ref) == policy.owner_of(ref)
    except (PolicyError, KeyError, ValueError):
        return False
