param([switch]$Stop)
$ErrorActionPreference = 'Stop'
if ($Stop) {
    docker compose -p smartrag-test -f docker-compose.test.yml down
    exit $LASTEXITCODE
}
docker compose -p smartrag-test -f docker-compose.test.yml up -d --wait
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
docker compose -p smartrag-test -f docker-compose.test.yml --profile tests run --build --rm tests
exit $LASTEXITCODE
