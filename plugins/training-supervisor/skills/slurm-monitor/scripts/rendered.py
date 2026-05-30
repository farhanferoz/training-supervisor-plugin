"""Fix selection + Hydra-override rendering for relaunch_with_fix.sh.

Pure functions; no side effects (no subprocess, no W&B calls). The bash
wrapper handles I/O (read run config from W&B, write the next_action.sh
file).
"""
from __future__ import annotations

import operator
import sys
from dataclasses import dataclass
from typing import Any

import yaml

AUTHORITY_AUTONOMOUS = {"aggressive"}
AUTHORITY_PROPOSE = {"balanced", "aggressive"}


@dataclass
class FixVerdict:
    id: str
    description: str
    risk: str               # safe | proposed | escalate
    action: str             # autonomous | propose | escalate | refused
    hydra_overrides: list[str]


def _flatten(d: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in d.items():
        key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            out.update(_flatten(v, key))
        else:
            out[key] = v
    return out


def _config_get(flat: dict[str, Any], *paths: str, default: Any = None) -> Any:
    for p in paths:
        if p in flat:
            return flat[p]
    return default


def _render(template: str, env: dict[str, Any]) -> str:
    """Replace each {{ expr }} with the result of eval(expr, env)."""
    out: list[str] = []
    i = 0
    while i < len(template):
        if template[i:i+2] == "{{":
            j = template.index("}}", i + 2)
            expr = template[i+2:j].strip()
            out.append(str(eval(expr, {"__builtins__": {}}, env)))  # noqa: S307
            i = j + 2
        else:
            out.append(template[i]); i += 1
    return "".join(out)


def _check_requires(req: list[str], env: dict[str, Any]) -> bool:
    ops = {">=": operator.ge, "<=": operator.le, ">": operator.gt,
           "<": operator.lt, "==": operator.eq, "!=": operator.ne}
    for cond in req:
        for sym, op in ops.items():
            if sym in cond:
                lhs_s, rhs_s = (s.strip() for s in cond.split(sym, 1))
                lhs = env.get(lhs_s)
                try:
                    rhs = float(rhs_s)
                except ValueError:
                    rhs = env.get(rhs_s)
                if lhs is None or not op(float(lhs), float(rhs)):
                    return False
                break
        else:
            # condition didn't contain a known operator; treat as truthy lookup
            if not env.get(cond.strip()):
                return False
    return True


def select_fix(
    *, registry_path: str, failure_class: str,
    run_config: dict[str, Any], authority: str,
) -> FixVerdict | None:
    """Pick the first applicable fix; render its overrides; classify action."""
    with open(registry_path) as f:
        reg = yaml.safe_load(f) or {}
    fixes = reg.get("fixes", {}).get(failure_class, [])

    flat = _flatten(run_config)
    env = {
        "batch_size": _config_get(flat,
            "datamodule.batch_size", "data.batch_size", "batch_size", default=0),
        "accumulate": _config_get(flat,
            "trainer.accumulate_grad_batches", "accumulate_grad_batches",
            default=1),
        "lr": _config_get(flat, "optimizer.lr", "optimizer.learning_rate",
            "learning_rate", default=None),
        "current_min_lr_ratio": _config_get(flat,
            "optimizer.min_lr_ratio", default=0.0),
    }

    for entry in fixes:
        if not _check_requires(entry.get("requires", []), env):
            continue
        risk = entry["risk"]
        if risk == "escalate":
            action = "escalate"
        elif risk == "safe" and authority in AUTHORITY_AUTONOMOUS:
            action = "autonomous"
        elif risk in ("safe", "proposed") and authority in AUTHORITY_PROPOSE:
            action = "propose"
        else:
            action = "refused"

        rendered_overrides = [_render(t, env) for t in entry.get("hydra_overrides", [])]
        return FixVerdict(
            id=entry["id"], description=entry["description"], risk=risk,
            action=action, hydra_overrides=rendered_overrides,
        )
    return None


def _read_run_config(wandb_run: str) -> dict[str, Any]:
    """Fetch the failed run's config from W&B. Returns {} on failure."""
    try:
        import wandb
        api = wandb.Api()
        # Caller is expected to pass entity/project via $WANDB_ENTITY /
        # $WANDB_PROJECT or as a fully-qualified id "entity/project/run_id".
        run = api.run(wandb_run)
        cfg = dict(run.config)
    except Exception as exc:  # noqa: BLE001
        print(f"rendered: WARN — could not read W&B config: {exc}",
              file=sys.stderr)
        return {}
    return cfg


def _write_next_action(
    *, path: str, template: str, ssh_host: str, overrides: list[str],
) -> None:
    """Render the relaunch_template and write an executable next_action.sh."""
    body = template.replace("{HOST}", ssh_host) \
                   .replace("{OVERRIDES}", " ".join(overrides))
    with open(path, "w") as f:
        f.write("#!/usr/bin/env bash\n# relaunch generated by rendered.py\n"
                "set -euo pipefail\n" + body + "\n")
    import os
    os.chmod(path, 0o755)


def _cli(argv: list[str] | None = None) -> int:
    import argparse
    import os
    p = argparse.ArgumentParser(prog="slurm-monitor.rendered")
    p.add_argument("--registry", required=True)
    p.add_argument("--wandb-run", required=True)
    p.add_argument("--failure-class", required=True)
    p.add_argument("--authority", required=True)
    p.add_argument("--ssh-host", required=True)
    p.add_argument("--relaunch-template", required=True)
    p.add_argument("--next-action", required=True)
    p.add_argument("--log-dir", required=True)
    args = p.parse_args(argv if argv is not None else sys.argv[1:])

    cfg = _read_run_config(args.wandb_run)
    verdict = select_fix(
        registry_path=args.registry, failure_class=args.failure_class,
        run_config=cfg, authority=args.authority,
    )
    log_path = os.path.join(args.log_dir, "fix_decision.md")
    if verdict is None:
        with open(log_path, "w") as f:
            f.write(f"# fix_decision\n\nNo applicable fix for "
                    f"failure_class={args.failure_class!r} under "
                    f"authority={args.authority!r}.\n")
        return 0

    _write_next_action(
        path=args.next_action, template=args.relaunch_template,
        ssh_host=args.ssh_host, overrides=verdict.hydra_overrides,
    )
    if verdict.action == "autonomous":
        # Marker file the bash wrapper checks before exec'ing next_action.sh.
        open(os.path.join(args.log_dir, ".autonomous"), "w").close()
    with open(log_path, "w") as f:
        f.write(
            f"# fix_decision\n\n"
            f"- id: {verdict.id}\n"
            f"- risk: {verdict.risk}\n"
            f"- action: {verdict.action}\n"
            f"- description: {verdict.description}\n"
            f"- hydra_overrides: {verdict.hydra_overrides}\n"
            f"- next_action: {args.next_action}\n"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
