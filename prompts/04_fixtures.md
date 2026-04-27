/skill:python-engineering

## Task: Create the fixtures directory

No skill invocation needed for this task — it is file content only, no Python code.

### Files to create

```
/root/challenge/fixtures/.env.example
/root/challenge/fixtures/config.yaml
/root/challenge/fixtures/dummy_private_key.pem
/root/challenge/fixtures/settings.json
```

These files exist so the security scanners have real targets to find.
They MUST contain fake/example values — never real credentials.

---

### `fixtures/.env.example`

```
# Example environment file — DO NOT USE IN PRODUCTION
DATABASE_URL=postgres://admin:supersecret123@localhost:5432/mydb
API_KEY=sk-1234567890abcdefghijklmnopqrstuvwxyz
SECRET_KEY=my-very-secret-django-key-do-not-use
AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE
AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY
REDIS_PASSWORD=redispassword123
DEBUG=true
```

---

### `fixtures/config.yaml`

```yaml
# Application configuration — example only
server:
  host: 0.0.0.0
  port: 8080
  debug: true

database:
  host: localhost
  port: 5432
  name: appdb
  user: dbuser
  password: mysecretpassword

security:
  ssl: false
  verify_ssl: false
  secret_key: hardcoded-secret-key-example

logging:
  level: DEBUG
```

---

### `fixtures/dummy_private_key.pem`

```
-----BEGIN RSA PRIVATE KEY-----
MIIEowIBAAKCAQEA0Z3VS5JJcds3xHn/ygWep4VEbCnFJOJ4hkMuA1TFBInmjHFP
ZFEQjIqcNFuOJpLJlwYZ9IEXAMPLE0000000000000000000000000000000000000
AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA
BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB
CCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCC
DDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDD
EXAMPLE/KEY/DO/NOT/USE/IN/PRODUCTION/THIS/IS/FAKE/DATA/ONLY====
-----END RSA PRIVATE KEY-----
```

---

### `fixtures/settings.json`

```json
{
  "app_name": "example-app",
  "version": "1.0.0",
  "debug": true,
  "api_key": "sk-examplekeydonotuse1234567890abcdef",
  "database": {
    "host": "0.0.0.0",
    "port": 5432,
    "password": "examplepassword123",
    "ssl": false
  },
  "auth": {
    "token": "bearer-token-example-do-not-use",
    "verify_tls": false
  }
}
```

---

### Constraint

Write these files with exactly the content above. The scanner tools will detect
patterns in these files. Do not add or remove secret-looking patterns — the
test coverage depends on them being present.
