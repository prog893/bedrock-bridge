# Releasing

Releases are cut by the maintainer, on request. A merged PR does not by itself trigger a release; several merged PRs are often shipped together.

1. On `main`, bump `__version__` in `bedrock_bridge/__init__.py` and commit it as `Bump version to X.Y.Z`. `pyproject.toml`, `--version` and the boto3 User-Agent all read this value.
2. Tag the commit `vX.Y.Z` (lightweight tag) and push `main` and the tag.
3. In [prog893/homebrew-tap](https://github.com/prog893/homebrew-tap), edit `Formula/bedrock-bridge.rb`: set `tag:` to `vX.Y.Z`, `revision:` to the output of `git rev-parse vX.Y.Z^{commit}`, and `version` to `X.Y.Z`. Homebrew checks that the tag resolves to that commit.
4. If dependencies changed, regenerate the resource blocks: with the formula in the tapped repo, run `brew update-python-resources Formula/bedrock-bridge.rb` from the tap root.
5. Test with `brew upgrade prog893/tap/bedrock-bridge`, then `bedrock-bridge --version`. Stop any running Homebrew bridge sessions first.
6. Commit the formula as `bedrock-bridge X.Y.Z` and push the tap.

Tags may be moved before 1.0 (`git tag -d`, `git push origin :refs/tags/vX.Y.Z`, retag, push). After moving a tag, update `revision:` in the formula.
