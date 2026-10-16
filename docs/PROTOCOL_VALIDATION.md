# Protocol probe

`tools/probe_tig_v2.py` captures complete TIG protocol inputs for a few
consecutive blocks and checks the qualifying-credit arithmetic and public
report parsing against them. It does not submit benchmarks, change a reward
destination, authenticate a member, or make any ledger or token movement, and
its output is integration input, not a health check of a running deployment.
The production observer, with persistent coverage cursors, database storage,
backup, redundancy and retention, is described in
[observation and selection](OBSERVATION_AND_SELECTION.md).

## Run and replay

From this repository, using Python 3.12 and its standard library:

```sh
python3 tools/probe_tig_v2.py \
  --output /tmp/community-pool-observations \
  --snapshots 2 --max-wait 240 \
  --reports-round 129 --reports-round 130

PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests/v2 -p 'test_protocol.py' -v
```

Use an empty output directory. The probe queries the latest block, its
algorithms/challenges/OPoW data, and the compact `/get-benchmarks` response for
every active OPoW player. A second block read must match the first. All active
benchmark IDs must have their precommit, bundle scores, and proof metadata.
The collected qualifier totals must agree at algorithm, player, and challenge
levels. Missing records, unknown fields needed for accounting, inconsistent
counts, stale blocks, and a block change prevent that observation from passing.

The compact player endpoint avoids fetching full nonce solutions and Merkle
proofs for every network benchmark. It covers the last 120 blocks;
the probe checks actual coverage against the active IDs on every capture,
instead of assuming that window will always cover every eligible benchmark.

Each compressed JSON archive contains the observed responses, retrieval
provenance, and a validation marker. Files are atomically replaced and synced
to disk. Failed attempts retain available partial evidence and are marked
incomplete. A missed height or inconsistent parent link prevents the run from
claiming consecutive coverage, even when both individual snapshots validate.
Source data is never filled with zeros or copied forward from an older block.

## Recorded fixtures

[`tests/v2/fixtures`](../tests/v2/fixtures) holds two consecutive mainnet
blocks captured this way, with their response provenance, and the public
report and arbitration responses for two rounds. `test_protocol.py` replays
them: the validator reconstructs exact fractional bundle credit using the
equal-sharing rule within each player/algorithm/track group, where higher
scores receive credit first and bundles tied at the boundary share the
remaining places equally. No attempt is made to recover TIG's randomly
selected winning bundle identities, and the active-score array index is only
a local credit identifier, not an original nonce or bundle index for fraud
evidence. The report parser joins reports and decisions by report ID and keeps
pending decisions, final `inconclusive`, final `reproducible` and upheld
`nonreproducible` distinct; unknown results or missing fields are errors. The
parser does not itself decide that an arbitration period has ended or release
or forfeit collateral.

These fixtures establish complete protocol inputs and arithmetic. Assigning
credit to pool members still requires the pool's immutable ownership records,
and recordings cannot substitute for observations of future reward rounds.
What the fixtures and the live deployment have and have not established is
summarised in [ROADMAP.md](ROADMAP.md#validated-so-far-and-not-yet).

## Network metadata discrepancy

The captured TIG block advertises chain ID `0x14a33` (84531), RPC URL
`https://mainnet.base.org`, and token address
`0x0c03ce270b4826ec62e7dd007f0b716068639f7b`.

A separate read-only RPC check returned chain ID `0x2105` (8453), and the
token's `decimals()` returned 18. Its requests and responses are preserved in
[`token-network.json`](../tests/v2/fixtures/token-network.json). Base's
[official chain ID documentation](https://docs.base.org/base-chain/api-reference/ethereum-json-rpc-api/eth_chainId)
also identifies 8453 as Base Mainnet.

The funds adapter therefore uses explicit deployment configuration, verifies it
against the RPC and token contract, and surfaces disagreement with TIG's
advertised metadata. The advertised chain ID is never copied into
wallet-signing messages, deposit attribution, or withdrawal checks. The custody
observer likewise reproduces a complete public token transfer and its wallet
balance change from archived RPC responses; see
[custody observation](CUSTODY_OBSERVER.md).

## What the probe does not establish

A record disappearing from a current feed is not proof of expiry; the
confirmed verification-failure feed has a recorded public fixture and adapter
tests, see [submission recovery](SUBMISSION_RECOVERY.md). An elapsed date or
an unsuccessful reports fetch is not a final-outcome signal, and both the
creation and the reporting round identifiers are preserved. Every deployment
must configure and verify its own pool account, custody wallet, token network
and confirmation policy before enabling monetary operations. Precommit
acceptance and rejection against a deployment, definitive expiry, the
creation/reporting-round boundary mapping and the path from final round
emissions to actual pool receipts are the checks listed in
[ROADMAP.md](ROADMAP.md).
