# Buy Source Code / Private Access

This project is sold as commercial source code.

## How Access Works

1. Buyer contacts the seller.
2. Seller provides demo, scope, and price.
3. Buyer completes payment.
4. Seller grants access using one of these methods:
   - Private GitHub repository invitation
   - Private zip/source release
   - Private deployment package

## Before Granting Access

Use this checklist:

- [ ] Confirm buyer identity and payment.
- [ ] Confirm license terms.
- [ ] Confirm whether support is included.
- [ ] Confirm allowed deployment count or organization scope.
- [ ] Send only a clean release package or invite to the private repo.
- [ ] Do not send `.env`, local databases, logs, cache files, `.venv`, or `node_modules`.

## Recommended Clean Zip Command

From a clean git worktree:

```bash
git archive --format=zip --output chatbot-enterprise-source.zip main
```

This uses `.gitattributes` export rules and avoids local-only ignored files.

## Private Repo Access

If selling via GitHub access:

- Invite only the buyer's GitHub account.
- Use least-privilege access.
- Remove access if the license expires or payment is reversed.
- Keep the repository private.

## Public Demo / Marketing Repo

For public marketing, create a separate repo containing only:

- README
- screenshots
- demo video link
- contact information
- feature list
- license notice

Do not publish this source repository as the public marketing repo.

## Contact

See [CONTACT.md](CONTACT.md).
