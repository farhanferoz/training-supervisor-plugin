"""Fix selection + Hydra-override rendering for relaunch_with_fix.sh.

Pure functions; no side effects (no subprocess, no W&B calls). The bash
wrapper handles I/O (read run config from W&B, write the next_action.sh
file).
"""
from __future__ import annotations

import argparse
import ast
import operator
import os
import shlex
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

AUTHORITY_AUTONOMOUS = {"aggressive"}
AUTHORITY_PROPOSE = {"balanced", "aggressive"}

_ALLOWED_RISK_VALUES = {"safe", "proposed", "escalate"}

# Allowed ast node types for the safe expression evaluator.
_ALLOWED_NODES = (
    ast.Expression,
    ast.Constant,    # covers Num + Str in older AST API
    ast.Name,
    ast.BinOp,
    ast.UnaryOp,
    ast.IfExp,
    ast.Compare,
    ast.BoolOp,
)

# Allowed operators for BinOp (no Pow — exponent overflow).
_ALLOWED_BINOPS = (ast.Add, ast.Sub, ast.Mult, ast.FloorDiv, ast.Mod)
# Allowed unary operators.
_ALLOWED_UNARYOPS = (ast.USub,)
# Allowed compare operators.
_ALLOWED_COMPAREOPS = (ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE)
# Allowed bool operators.
_ALLOWED_BOOLOPS = (ast.And, ast.Or)


def _check_node(node: ast.AST) -> None:
    """Raise ValueError if *node* contains any disallowed construct."""
    # AST context/operator singletons (Load, Store, Del, Add, etc.) are
    # visited as children but are not expression nodes; skip them here —
    # their parent nodes are checked above for allowed operator types.
    if isinstance(node, (ast.expr_context, ast.operator, ast.unaryop,
                         ast.boolop, ast.cmpop)):
        return
    if not isinstance(node, _ALLOWED_NODES):
        msg = f"disallowed expression element {type(node).__name__}"
        raise ValueError(msg)
    if isinstance(node, ast.BinOp) and not isinstance(node.op, _ALLOWED_BINOPS):
        msg = f"disallowed binary operator {type(node.op).__name__}"
        raise ValueError(msg)
    if isinstance(node, ast.UnaryOp) and not isinstance(node.op, _ALLOWED_UNARYOPS):
        msg = f"disallowed unary operator {type(node.op).__name__}"
        raise ValueError(msg)
    if isinstance(node, ast.Compare):
        for op in node.ops:
            if not isinstance(op, _ALLOWED_COMPAREOPS):
                msg = f"disallowed compare operator {type(op).__name__}"
                raise ValueError(msg)
    if isinstance(node, ast.BoolOp) and not isinstance(node.op, _ALLOWED_BOOLOPS):
        msg = f"disallowed bool operator {type(node.op).__name__}"
        raise ValueError(msg)
    for child in ast.iter_child_nodes(node):
        _check_node(child)


_MAX_RESULT_LEN = 4096


def _safe_eval(expr: str, env: dict[str, Any]) -> Any:
    """Evaluate *expr* against *env* using a whitelist AST visitor.

    Allowed: constants, name lookups, arithmetic (+/-/*//%), unary minus,
    ternary IfExp, comparisons (==, !=, <, <=, >, >=), boolean And/Or.
    Disallowed: everything else (attribute access, subscript, calls, Pow, …).

    Additional guards:
    - Result strings/bytes are capped at _MAX_RESULT_LEN chars to prevent
      string-repetition DoS (e.g. ``"A" * 100000``).
    - TypeError from arithmetic on non-numeric operands (e.g. str * int) is
      re-raised as ValueError to surface a clear message.
    """
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as exc:
        msg = f"invalid expression syntax: {expr!r}"
        raise ValueError(msg) from exc
    _check_node(tree)

    # eval() against a restricted env with no builtins.
    # The whitelist visitor above already rejected any dangerous constructs.
    try:
        result = eval(  # noqa: S307
            compile(tree, "<expr>", "eval"),
            {"__builtins__": {}},
            env,
        )
    except TypeError as exc:
        msg = f"template arithmetic on non-numeric operand: {exc}"
        raise ValueError(msg) from exc

    if isinstance(result, (str, bytes)) and len(result) > _MAX_RESULT_LEN:
        msg = (
            f"template result too large ({len(result)} chars; cap={_MAX_RESULT_LEN})"
        )
        raise ValueError(msg)
    return result


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
    """Replace each {{ expr }} with the result of _safe_eval(expr, env).

    Raises ValueError on unmatched '{{' or disallowed expressions.
    """
    out: list[str] = []
    i = 0
    while i < len(template):
        if template[i:i+2] == "{{":
            try:
                j = template.index("}}", i + 2)
            except ValueError:
                msg = f"unmatched '{{{{' in template: {template!r}"
                raise ValueError(msg)  # noqa: B904
            expr = template[i+2:j].strip()
            out.append(str(_safe_eval(expr, env)))
            i = j + 2
        else:
            out.append(template[i])
            i += 1
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
                # Guard: if either operand is None the condition cannot be satisfied.
                if lhs is None or rhs is None:
                    return False
                if not op(float(lhs), float(rhs)):
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
    if reg.get("version") != 1:
        print(
            f"warning: fix registry version != 1 (got {reg.get('version')!r})",
            file=sys.stderr,
        )
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
        # Validate risk value against allowed set.
        if risk not in _ALLOWED_RISK_VALUES:
            fix_id = entry.get("id", "<unknown>")
            msg = (
                f"registry entry {fix_id!r} has unknown risk={risk!r}; "
                f"allowed: safe|proposed|escalate"
            )
            raise ValueError(msg)
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
    """Render the relaunch_template and write an executable next_action.sh.

    Two quoting layers are applied so the script is safe both locally and on
    the remote shell:

    1. Each override is shlex.quote()'d individually so that override values
       containing shell metacharacters (semicolons, spaces, etc.) are treated
       as single tokens by the remote shell.
    2. The complete remote command string (autocast … <overrides>) is then
       wrapped in a second shlex.quote() so that the local shell hands it to
       ssh as one argument.  The resulting script looks like::

           ssh -- login.example 'autocast epd --mode slurm '\''datamodule.batch_size=32'\'''

       The ``--`` separator prevents ssh from interpreting a hostname that
       begins with ``-`` as an option flag (H-new / hostname-option injection).
    """
    if ssh_host.startswith("-"):
        msg = f"ssh_host must not start with '-' (got {ssh_host!r}); this would be interpreted as an ssh option"
        raise ValueError(msg)

    quoted_overrides = " ".join(shlex.quote(o) for o in overrides)
    # Build the remote command string, then quote the whole thing for the
    # outer (local) shell so ssh receives it as a single argument.
    remote_cmd_str = template.replace("{HOST}", "").replace("{OVERRIDES}", quoted_overrides).strip()
    # If the template has {HOST} it is used as an ssh target; reconstruct the
    # correct form: ssh -- <host> '<remote_cmd>'.
    if "{HOST}" in template:
        # template may be e.g. "ssh {HOST} autocast epd {OVERRIDES}" — strip
        # the ssh prefix and host placeholder then re-form with safe quoting.
        # Support both "ssh {HOST} <cmd>" and "ssh {HOST} -- <cmd>".
        import re as _re
        # Remove leading "ssh {HOST} [--] " from the template to isolate the
        # remote command portion.
        remote_part = _re.sub(r"^ssh\s+\{HOST\}\s+(?:--\s+)?", "", template).strip()
        remote_cmd = remote_part.replace("{OVERRIDES}", quoted_overrides)
        body = f"ssh -- {shlex.quote(ssh_host)} {shlex.quote(remote_cmd)}"
    else:
        body = remote_cmd_str

    with open(path, "w") as f:
        f.write("#!/usr/bin/env bash\n# relaunch generated by rendered.py\n"
                "set -euo pipefail\n" + body + "\n")
    os.chmod(path, 0o755)


def _cli(argv: list[str] | None = None) -> int:
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

    # Validate --registry path: must exist and have a YAML suffix.
    registry_path = Path(args.registry).resolve(strict=True)
    if registry_path.suffix not in {".yaml", ".yml"}:
        msg = f"--registry must be a .yaml or .yml file; got {registry_path}"
        raise ValueError(msg)

    cfg = _read_run_config(args.wandb_run)
    verdict = select_fix(
        registry_path=str(registry_path), failure_class=args.failure_class,
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
        with open(os.path.join(args.log_dir, ".autonomous"), "w"):
            pass
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
