# Clinical fitting admin login

Clinical fitting (`/`) supports username/password sign-in and retains the existing access-code option. The synthetic-only local staging runner provisions `nso` / `2026nso` for checking assigned synthetic patients. No default account is enabled on a normal production server.

For a deployed backend, configure:

- `NSO_CLINICAL_ADMIN_USERNAME`: username (defaults to `nso`).
- `NSO_CLINICAL_ADMIN_PASSWORD_HASH`: salted PBKDF2-SHA256 hash, generated with `clinical_admin_auth.password_hash()` on the backend. Do not put the password in frontend environment variables.
- `NSO_CLINICAL_ADMIN_PATIENT_IDS`: JSON array of authorized patient IDs; wildcard scope is rejected.

The `clinical_admin` role allows reading assigned records, clinical fitting and design approval. It does not grant model deployment, research training or engineering permissions. Existing clinical validation and manufacturing gates still apply.

Sessions expire after one hour, live only in server memory and are invalidated on logout, password rotation or backend restart. The browser keeps the token in React memory and signs out after 15 minutes of inactivity. The current implementation requires one backend worker; use a shared session store before configuring multiple workers or replicas. Login is limited to 10 attempts per client address per five-minute server time bucket. Production hosting must use HTTPS.

Verification: 16 backend authentication/security tests passed, 14 frontend component tests passed and Next.js production build succeeded on 2026-10-30.
