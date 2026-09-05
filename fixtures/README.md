# Private fixture installation

The private `fixed-v1` puzzle files are distributed as an encrypted GitHub Release asset and are excluded from Git history.

```bash
bash scripts/install-fixtures.sh
```

- Release: `fixtures-v1`
- Asset: `turtlebench-fixed-v1.zip`
- ZIP password: `123456`
- SHA-256: `c28746c7b8296a2b8eb36aef6c6cff5ae9418283409c291eaac139c772646069`

The script installs the suite to `fixtures/fixed-v1/`, which remains ignored by Git.
