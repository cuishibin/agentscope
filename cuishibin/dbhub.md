```bash
export DOCKER_HOST=tcp://10.10.1.229:2375

docker run --rm --init \
  --name dbhub \
  --publish 8080:8080 \
  bytebase/dbhub \
  --transport http \
  --port 8080 \
  --allowed-hosts "10.12.1.229,localhost,127.0.0.1" \
  --dsn "postgresql://nginx_vllm:nginx_vllm@10.10.1.226:5432/nginx_vllm?sslmode=disable"
```

