# ADR 0004: SeaweedFS replaces unavailable archived MinIO images

Accepted 2026-11-04. The requested MinIO image pull failed with repository access denied.
[MinIO upstream](https://github.com/minio/minio) is archived; its last security release
[instructs building from source](https://github.com/minio/minio/releases/tag/RELEASE.2025-10-15T17-29-55Z).
Use the maintained S3-compatible [SeaweedFS 4.52 release](https://github.com/seaweedfs/seaweedfs/releases/tag/4.52)
in local Compose instead of adopting an archived source build or an untrusted mirror.

`weed mini` seeds credentials from environment variables and serves S3 on port 8333;
see the [official quick start](https://github.com/seaweedfs/seaweedfs#quick-start).
The application's boto3 adapter and private bucket contract remain S3-compatible.
An existing MinIO or hosted S3 deployment can use the same environment configuration.
SeaweedFS mini is a local development service, not an HA production storage topology.
