# Keycloak: the IdP performs the on-behalf-of exchange (D-041)

Optional, local, $0. From `M3/`:

```bash
make keycloak-up      # generate throwaway synthetic credentials (~/.claimsense/keycloak.json, 0600), start, build the realm
make keycloak-proof   # evidence/19: 13 live checks
make keycloak-down
```

```
alice ──sign-in──▶ Keycloak (claimsense-console)      token: aud = orchestrator
orchestrator ──RFC 8693 exchange──▶ Keycloak           token: aud = claimsense-door, azp = orchestrator,
                                                              scope = get_claim search_policy_clauses, 5 min
orchestrator ──tools/call──▶ the door                  IdPExchange verifies (JWKS, iss, aud, azp, directory),
                                                       TOKEN_SCOPE = the exchanged scope ─▶ _authorize
```

The door still applies its grants (deny-by-default) and entitlement: the IdP's scope narrows, never widens.
`confirm_recommendation`, `read_audit` and `ticket_webhook` do not exist as scopes in the realm, so they cannot be
delegated at all. Keycloak runs in dev mode here (synthetic sandbox only).
