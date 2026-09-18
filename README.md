# GroundedVerdictRegistry

Standalone GenLayer Intelligent Contract.

Flow: `open_case` → `add_source` → `seal_sources` → `adjudicate` → `challenge`

Status: OPEN → SEALED → SUPPORTED | REFUTED | INCONCLUSIVE → CHALLENGED

## Files
- `contracts/GroundedVerdictRegistry.py` — contract for GenLayer Studio
- `web/index.html` — operator checklist UI

## Deploy
1. Open https://studio.genlayer.com
2. New contract → paste `contracts/GroundedVerdictRegistry.py`
3. Deploy
4. Run the 3 cases below

## Studio cases
1. question: The example.org page refers to IANA.  
   rubric: SUPPORTED only if the visible page text mentions IANA.  
   sources: https://example.org  
   expect: SUPPORTED
2. question: example.org is the official homepage of the United Nations.  
   rubric: REFUTED if the page is a generic example and does not present itself as the UN.  
   sources: https://example.org  
   expect: REFUTED
3. sources: https://this-domain-should-not-resolve-genlayer-test.invalid  
   expect: INCONCLUSIVE

## Local UI
python -m http.server 8080 --directory web
