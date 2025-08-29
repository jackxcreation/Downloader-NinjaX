# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 2.0.x   | ✅ Yes             |
| 1.x.x   | ❌ No              |

## Reporting a Vulnerability

We take security vulnerabilities seriously. If you discover a security issue, please follow these steps:

### 🔒 Private Disclosure

**DO NOT** create a public GitHub issue for security vulnerabilities.

Instead, please email us at: **jodjack64@gmail.com**

Include the following information:
- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (if any)

### ⏱️ Response Timeline

- **Initial Response**: Within 24-48 hours
- **Status Update**: Within 1 week
- **Fix Timeline**: 2-4 weeks depending on severity

### 🛡️ Security Measures

Our application implements:

- Input validation and sanitization
- Rate limiting per IP address
- CORS configuration
- Security headers (HSTS, CSP, etc.)
- File path traversal protection
- Automatic cleanup of temporary files

### 🏆 Recognition

We appreciate security researchers who help keep our users safe. Contributors will be:

- Acknowledged in our security hall of fame (with permission)
- Credited in release notes
- Given priority support for future reports

### 📋 Security Checklist for Contributors

Before submitting code:

- [ ] All user inputs are validated
- [ ] No hardcoded credentials
- [ ] Error messages don't leak sensitive info
- [ ] File operations are secure
- [ ] Dependencies are up to date

## Contact

For security-related questions: **jodjack64@gmail.com**

---
Last updated: 2025-08-29
