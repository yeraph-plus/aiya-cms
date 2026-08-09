"""S3 object storage adapter (planned).

Target: ``inc.capabilities.assets.ports.ObjectStorageProvider``.

Planned integration: AWS S3 (or S3-compatible) via boto3. Must own
credentials, presigned upload/read URLs, stat and idempotent delete
(missing object treated as success per the Port contract). Do not
implement until the provider contract is frozen; this file must stay
import-safe and side-effect free.
"""
