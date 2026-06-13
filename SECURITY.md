# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| Latest (main branch) | Yes |

## Reporting a Vulnerability

If you discover a security vulnerability in Slowbooks Pro, please report it responsibly:

1. **Do NOT open a public issue** for security vulnerabilities
2. Use GitHub's [private vulnerability reporting](https://github.com/VonHoltenCodes/SlowBooks-Pro-2026/security/advisories/new) to submit a report
3. Or email **trentonvonholten@gmail.com** with details

### What to include

- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (if any)

### Response timeline

- **Acknowledgment**: Within 48 hours
- **Assessment**: Within 1 week
- **Fix**: As soon as practical, depending on severity

## Scope

This policy applies to the Slowbooks Pro 2026 codebase. Security issues in third-party dependencies should be reported to those projects directly (though we appreciate a heads-up).

## Known considerations

- Slowbooks is designed to run on a **local network or single machine** — it has no built-in authentication. Do not expose it to the public internet without adding an auth layer (reverse proxy, VPN, etc.)
- OAuth tokens (Stripe, QBO) are stored in the PostgreSQL database — secure your database access accordingly
- SMTP passwords are stored in plaintext in the settings table — same as above
