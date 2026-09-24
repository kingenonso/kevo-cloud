import re

FILES = [
    "static/account.html",
    "static/browse.html",
    "static/dashboard.html",
    "static/deal-alerts.html",
    "static/deal-health.html",
    "static/deal-room.html",
    "static/eligibility.html",
    "static/evidence.html",
    "static/funding.html",
    "static/kyc.html",
    "static/ledger.html",
    "static/lending.html",
    "static/listing-detail.html",
    "static/listings.html",
    "static/market.html",
    "static/rofr.html",
    "static/settlement.html",
    "static/tender-offer.html",
    "static/transactions.html",
]

NEW_LINK_TEMPLATE = '{indent}<a href="/app/cost-calculator.html" class="text-xs uppercase tracking-wide text-slate-500 hover:text-white transition-colors">Cost Calculator</a>\n'

pattern = re.compile(r'^([ \t]*)<a href="/app/account\.html"[^\n]*>Account</a>\n', re.MULTILINE)

modified = []
skipped = []

for path in FILES:
    with open(path, "r") as f:
        content = f.read()

    if "cost-calculator.html" in content:
        skipped.append((path, "already has cost-calculator link"))
        continue

    matches = list(pattern.finditer(content))
    if len(matches) != 1:
        skipped.append((path, f"found {len(matches)} Account nav matches, expected exactly 1"))
        continue

    match = matches[0]
    indent = match.group(1)
    insertion = NEW_LINK_TEMPLATE.format(indent=indent)
    new_content = content[:match.start()] + insertion + content[match.start():]

    with open(path, "w") as f:
        f.write(new_content)

    modified.append(path)

print(f"Modified ({len(modified)}):")
for p in modified:
    print(" ", p)

print(f"\nSkipped ({len(skipped)}):")
for p, reason in skipped:
    print(" ", p, "-", reason)
