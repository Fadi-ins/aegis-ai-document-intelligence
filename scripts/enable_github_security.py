"""Apply Aegis owner settings using the owner's locally authenticated GitHub CLI."""
import json
import subprocess
import sys

REPO = "Fadi-ins/aegis-ai-document-intelligence"
ENDPOINT = "repos/" + REPO
CHECKS = ("backend", "Analyze (python)", "Analyze (actions)", "Secret scan",
          "Python dependency audit", "Dependency review", "Container vulnerability scan")


def api(method, path="", data=None):
    args = ["gh", "api", "--hostname", "github.com", "--method", method, ENDPOINT + path]
    if data is not None:
        args.extend(["--input", "-"])
    result = subprocess.run(args, input=json.dumps(data) if data is not None else None,
                            text=True, capture_output=True, check=False)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or f"{method} {path} failed")
    return json.loads(result.stdout) if result.stdout.strip() else None


def protect_main():
    name = "Aegis main security checks"
    rules = [
        {"type": "deletion"}, {"type": "non_fast_forward"},
        {"type": "pull_request", "parameters": {
            "required_approving_review_count": 0, "dismiss_stale_reviews_on_push": False,
            "require_code_owner_review": False, "require_last_push_approval": False,
            "required_review_thread_resolution": True}},
        {"type": "required_status_checks", "parameters": {
            "strict_required_status_checks_policy": True,
            "required_status_checks": [{"context": c, "integration_id": 15368} for c in CHECKS]}},
        {"type": "code_scanning", "parameters": {"code_scanning_tools": [
            {"tool": "CodeQL", "alerts_threshold": "errors", "security_alerts_threshold": "high_or_higher"}]}}
    ]
    config = {"name": name, "target": "branch", "enforcement": "active", "rules": rules,
              "conditions": {"ref_name": {"include": ["refs/heads/main"], "exclude": []}},
              "bypass_actors": []}
    existing = api("GET", "/rulesets?includes_parents=false&per_page=100")
    if not any(r["name"] == name for r in existing):
        api("POST", "/rulesets", config)
    # Check effective rules without rewriting any settings the owner already configured.
    active = api("GET", "/rules/branches/main")
    types = {r["type"] for r in active}
    if not {r["type"] for r in rules} <= types:
        raise RuntimeError("A required rule is inactive. Inspect the repository rulesets.")
    checks = {c["context"] for r in active if r["type"] == "required_status_checks"
              for c in r["parameters"]["required_status_checks"] if c.get("integration_id") == 15368}
    if not set(CHECKS) <= checks:
        raise RuntimeError("Required GitHub Actions checks are missing from the active rules.")


def enable_alerts():
    api("PUT", "/vulnerability-alerts")
    api("GET", "/vulnerability-alerts")


def enable_fixes():
    api("PUT", "/automated-security-fixes")
    if not api("GET", "/automated-security-fixes")["enabled"]:
        raise RuntimeError("GitHub has not enabled automated security fixes.")


def enable_private_reports():
    api("PUT", "/private-vulnerability-reporting")
    if not api("GET", "/private-vulnerability-reporting")["enabled"]:
        raise RuntimeError("Private reporting is still disabled.")


def secret_setting(key):
    api("PATCH", data={"security_and_analysis": {key: {"status": "enabled"}}})
    if api("GET").get("security_and_analysis", {}).get(key, {}).get("status") != "enabled":
        raise RuntimeError(f"GitHub has not confirmed {key}.")


def restrict_token():
    desired = {"default_workflow_permissions": "read", "can_approve_pull_request_reviews": False}
    route = "/actions/permissions/workflow"
    api("PUT", route, desired)
    current = api("GET", route)
    if not all(current.get(k) == v for k, v in desired.items()):
        raise RuntimeError("GitHub has not confirmed restricted token permissions.")


def main():
    repo = api("GET")
    if not repo["permissions"].get("admin") or repo["private"] or repo["default_branch"] != "main":
        raise RuntimeError("This command requires owner access to the public Aegis repository on main.")
    tasks = [("Dependabot alerts", enable_alerts), ("Dependabot security updates", enable_fixes),
             ("Private vulnerability reporting", enable_private_reports),
             ("Secret scanning", lambda: secret_setting("secret_scanning")),
             ("Push protection", lambda: secret_setting("secret_scanning_push_protection")),
             ("Extended secret patterns", lambda: secret_setting("secret_scanning_non_provider_patterns")),
             ("Read-only workflow tokens", restrict_token), ("Protected main", protect_main)]
    failed = False
    for label, task in tasks:
        try:
            task()
            print(f"Verified: {label}")
        except RuntimeError as error:
            print(f"Unverified: {label} - {error}", file=sys.stderr)
            failed = True
    return int(failed)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (FileNotFoundError, RuntimeError) as error:
        sys.exit(str(error))
