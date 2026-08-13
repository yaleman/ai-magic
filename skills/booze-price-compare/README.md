# booze-price-compare

Codex skill for comparing packaged-booze prices across configured Australian retailers.

## Install

User-level:

```bash
mkdir -p ~/.agents/skills
cp -R booze-price-compare ~/.agents/skills/
```

Repo-scoped:

```text
<repo>/.agents/skills/booze-price-compare/
```

Invoke with:

```text
$booze-price-compare
```

Example:

```text
$booze-price-compare Compare Jack Daniel's Old No. 7 and Gentleman Jack across
Dan Murphy's, BWS, and Bob's Bulk Booze. Include every bottle size you can verify
and rank the table by price per litre.
```

Docs:
- https://developers.openai.com/codex/build-skills
- https://developers.openai.com/codex/customization/overview
