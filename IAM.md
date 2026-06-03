# IAM permissions for bedrock-bridge

The principal (IAM user, role, or SSO permission set) running `bedrock-bridge` needs to:

1. Identify itself (preflight sanity check)
2. Read foundation-model and inference-profile metadata (preflight per-model verification)
3. Invoke Bedrock Converse / ConverseStream against the configured models

Below is a minimal templated policy. Replace `<MAIN_MODEL_ID>` and `<LIGHT_MODEL_ID>` with the IDs you intend to use; remove the light statement if you don't configure `BEDROCK_BRIDGE_MODEL_LIGHT`.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "Identity",
      "Effect": "Allow",
      "Action": "sts:GetCallerIdentity",
      "Resource": "*"
    },
    {
      "Sid": "BedrockMetadata",
      "Effect": "Allow",
      "Action": [
        "bedrock:GetFoundationModel",
        "bedrock:GetInferenceProfile"
      ],
      "Resource": "*"
    },
    {
      "Sid": "BedrockInvokeMain",
      "Effect": "Allow",
      "Action": [
        "bedrock:InvokeModel",
        "bedrock:InvokeModelWithResponseStream",
        "bedrock:Converse",
        "bedrock:ConverseStream"
      ],
      "Resource": [
        "arn:aws:bedrock:*::foundation-model/<MAIN_MODEL_ID>",
        "arn:aws:bedrock:*:*:inference-profile/<MAIN_MODEL_ID>"
      ]
    },
    {
      "Sid": "BedrockInvokeLight",
      "Effect": "Allow",
      "Action": [
        "bedrock:InvokeModel",
        "bedrock:InvokeModelWithResponseStream",
        "bedrock:Converse",
        "bedrock:ConverseStream"
      ],
      "Resource": [
        "arn:aws:bedrock:*::foundation-model/<LIGHT_MODEL_ID>",
        "arn:aws:bedrock:*:*:inference-profile/<LIGHT_MODEL_ID>"
      ]
    }
  ]
}
```

## Notes

- **Foundation model vs inference profile.** Pure Bedrock IDs like `moonshotai.kimi-k2.5` resolve to `foundation-model/<id>`. Cross-region inference profiles (IDs starting with `global.`, `us.`, `eu.`, `apac.`) resolve to `inference-profile/<id>`. Including both ARNs above covers either case without having to know which one you'll use.
- **Cross-region inference profiles fan out.** A `global.*` profile may invoke the underlying foundation model in any region. If you scope by region, also allow the foundation model in those regions, or keep `*` as in the template.
- **Anthropic IDs auto-prefix.** `bedrock-bridge` rewrites `anthropic.claude-...` to `global.anthropic.claude-...` before calling Bedrock. Grant the inference-profile ARN to match.
- **Model access is separate from IAM.** You also need to enable model access in the Bedrock console (Foundation models → Model access) for each model in your account. IAM permissions alone are not sufficient.
- **Wider catalog?** If you want to swap models without editing the policy, broaden `Resource` to `arn:aws:bedrock:*::foundation-model/*` and `arn:aws:bedrock:*:*:inference-profile/*`. Trade-off: any model your account has been granted access to becomes invocable.
