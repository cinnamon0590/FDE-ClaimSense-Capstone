"""Stack-choice matrix for ClaimSense at AutoSure Insurance (stdlib only).

Method adapted from the course's W14 notebook §4 (weighted dimensions, then show when the
answer flips). Scores 1–5 are the FDE's judgment for THIS client; the weights and every score
are written down so the reasoning can be challenged line by line.

    python3 -I stack_matrix.py
"""
DIMENSIONS = {                    # weight: why it matters at AutoSure
    "brief_standard":     0.25,   # the cohort technology standard: OpenAI Agents SDK, containers, AWS
    "client_platform":    0.20,   # AutoSure hosts on AWS (brief: hosting, observability, recovery on AWS)
    "typed_output":       0.15,   # strict structured output for the DecisionCard (brief: "typed, verifiable")
    "data_path_control":  0.15,   # does claim text stay inside the client's cloud? (subprocessor risk)
    "identity_rbac":      0.10,   # Cognito/IAM story for per-user scope + audit
    "cost":               0.05,
    "ecosystem_maturity": 0.10,   # SDK, tracing, eval tooling, hiring signal
}

STACKS = {
    "OpenAI Agents SDK + OpenAI API, hosted on AWS (ECS, Lambda, S3, OpenSearch, Cognito)": dict(
        brief_standard=5, client_platform=5, typed_output=5, data_path_control=3, identity_rbac=5, cost=4, ecosystem_maturity=5),
    "OpenAI Agents SDK + Claude on Amazon Bedrock (LiteLLM bridge), all in AWS": dict(
        brief_standard=3, client_platform=5, typed_output=4, data_path_control=5, identity_rbac=5, cost=4, ecosystem_maturity=4),
    "OpenAI Agents SDK + Azure OpenAI / Foundry, hosted on Azure": dict(
        brief_standard=3, client_platform=2, typed_output=5, data_path_control=4, identity_rbac=4, cost=3, ecosystem_maturity=5),
    "Google ADK + Gemini, hosted on GCP": dict(
        brief_standard=1, client_platform=2, typed_output=4, data_path_control=4, identity_rbac=3, cost=5, ecosystem_maturity=4),
}


def score(stacks, dims):
    w = sum(dims.values())
    return {n: sum(s[d] * dims[d] for d in dims) / w for n, s in stacks.items()}


def show(title, stacks, dims):
    sc = score(stacks, dims)
    print("=" * 100); print(title); print("=" * 100)
    short = {d: d[:10] for d in dims}
    print(f"{'Stack':58}" + "".join(f"{short[d]:>11}" for d in dims) + f"{'WTD':>7}")
    for n, s in sorted(stacks.items(), key=lambda kv: -sc[kv[0]]):
        print(f"{n[:57]:58}" + "".join(f"{s[d]:>11}" for d in dims) + f"{sc[n]:>7.2f}")
    win = max(sc, key=sc.get)
    print(f"→ winner: {win}  ({sc[win]:.2f})")
    return win


def main():
    print("weights: " + ", ".join(f"{d}={w}" for d, w in DIMENSIONS.items()) + "\n")
    show("STACK-CHOICE MATRIX — ClaimSense at AutoSure (AWS-hosted motor insurer)", STACKS, DIMENSIONS)

    print("\nWHEN THE ANSWER FLIPS (same candidates, one changed condition):")
    # 1. Security forbids an external model subprocessor: claim text must not leave the AWS account.
    strict = dict(DIMENSIONS, data_path_control=0.40, brief_standard=0.10)
    w1 = max(score(STACKS, strict).items(), key=lambda kv: kv[1])
    print(f"  Security forbids an external model provider (data_path_control weight 0.40) → {w1[0][:60]}  ({w1[1]:.2f})")
    # 2. AutoSure turns out to be a Microsoft/Entra shop.
    ms = {n: dict(s, client_platform=(5 if "Azure" in n else 2)) for n, s in STACKS.items()}
    w2 = max(score(ms, DIMENSIONS).items(), key=lambda kv: kv[1])
    print(f"  AutoSure is M365/Entra-first and hosts on Azure                     → {w2[0][:60]}  ({w2[1]:.2f})")
    print("\nThe harness (OpenAI Agents SDK, the deterministic boundary, the eval gate) is portable across")
    print("all four; the model provider and cloud are a client-fit decision. Flip trigger is logged in DECISIONS D-009.")


if __name__ == "__main__":
    main()
