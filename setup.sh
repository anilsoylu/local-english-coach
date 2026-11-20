#!/usr/bin/env bash
# One-shot install on Linux with an NVIDIA GPU and Docker. Safe to re-run.
#   sudo ./setup.sh               # serve on 127.0.0.1 (this machine only)
#   sudo ./setup.sh --tailscale   # serve on this machine's Tailscale IP (your other devices)
#   sudo ./setup.sh --host IP --port N
# What it does: installs Ollama natively (if missing) with the tuned settings in
# deploy/ollama.override.conf, picks models for your VRAM, writes config.yaml if it doesn't exist,
# pulls the models, starts the app with Docker Compose (auto-starts on boot) and adds a daily backup.
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
HOST="" PORT=""
while [ $# -gt 0 ]; do
  case "$1" in
    --tailscale) HOST="$(tailscale ip -4 | head -1)" ;;
    --host) HOST="$2"; shift ;;
    --port) PORT="$2"; shift ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done

[ "$(id -u)" -eq 0 ] || { echo "run with sudo" >&2; exit 1; }
RUN_USER="${SUDO_USER:-root}"
RUN_UID="$(id -u "$RUN_USER")" RUN_GID="$(id -g "$RUN_USER")"
say() { printf '\n==> %s\n' "$*"; }

command -v docker >/dev/null && docker compose version >/dev/null 2>&1 \
  || { echo "Docker with the compose plugin is required: https://docs.docker.com/engine/install/" >&2; exit 1; }

say "GPU"
VRAM_MIB=0
if command -v nvidia-smi >/dev/null; then
  nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader
  VRAM_MIB="$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits | head -1 | tr -d ' ')"
else
  echo "No NVIDIA GPU found. Models will run on the CPU and replies will be slow."
fi
RAM_GIB="$(awk '/MemTotal/ {printf "%d", $2/1048576}' /proc/meminfo)"
echo "VRAM ${VRAM_MIB} MiB, RAM ${RAM_GIB} GiB"

# Measured on an RTX 3070 8 GB (see README). Smaller cards are a best guess: run the bench.
if [ "$VRAM_MIB" -ge 7500 ]; then CHAT=gemma4:e4b; else CHAT=gemma4:e2b; fi
if [ "$VRAM_MIB" -ge 7500 ] && [ "$RAM_GIB" -ge 28 ]; then ANALYSIS=gemma4:26b-a4b; else ANALYSIS="$CHAT"; fi

say "Ollama"
if ! command -v ollama >/dev/null; then
  # Private temp file: a fixed /tmp path could be pre-planted by another local user while we run as root.
  INSTALLER="$(mktemp)"
  curl -fsSL https://ollama.com/install.sh -o "$INSTALLER"
  sh "$INSTALLER"
  rm -f "$INSTALLER"
fi
install -D -m 644 "$DIR/deploy/ollama.override.conf" /etc/systemd/system/ollama.service.d/override.conf
systemctl daemon-reload
systemctl enable ollama >/dev/null 2>&1 || true
systemctl restart ollama
for _ in $(seq 1 30); do curl -sf http://127.0.0.1:11434/api/version >/dev/null && break; sleep 1; done
ollama --version

say "config.yaml"
if [ ! -f "$DIR/config.yaml" ]; then
  cat > "$DIR/config.yaml" <<EOF
# Written by setup.sh. See config.example.yaml for every option.
learner:
  name: ""
  level: A2
  about: ""
models:
  chat: $CHAT
  analysis: $ANALYSIS
server:
  host: ${HOST:-127.0.0.1}
  port: ${PORT:-8765}
EOF
  echo "created (edit learner: name/about to personalize)"
else
  echo "kept existing config.yaml"
  [ -n "$HOST" ] && sed -i "s/^  host: .*/  host: $HOST/" "$DIR/config.yaml"
  [ -n "$PORT" ] && sed -i "s/^  port: .*/  port: $PORT/" "$DIR/config.yaml"
fi
read_cfg() { awk -v k="  $1:" 'index($0, k) == 1 {sub(k, ""); gsub(/[ "]/, ""); print; exit}' "$DIR/config.yaml"; }
CHAT="$(read_cfg chat)"; ANALYSIS="$(read_cfg analysis)"
CFG_HOST="$(read_cfg host)"; CFG_PORT="$(read_cfg port)"
echo "chat=$CHAT analysis=$ANALYSIS listen=$CFG_HOST:$CFG_PORT"

say "Models"
for m in $(printf '%s\n' "$CHAT" "$ANALYSIS" | sort -u); do ollama pull "$m"; done

say "App (Docker Compose)"
printf 'COACH_UID=%s\nCOACH_GID=%s\n' "$RUN_UID" "$RUN_GID" > "$DIR/.env"
install -d -o "$RUN_USER" -g "$RUN_GID" "$DIR/data"
chown "$RUN_USER:$RUN_GID" "$DIR/config.yaml" "$DIR/.env"
systemctl enable docker >/dev/null 2>&1 || true
( cd "$DIR" && docker compose up -d --build coach )
for _ in $(seq 1 60); do curl -sf "http://$CFG_HOST:$CFG_PORT/api/scenarios" >/dev/null && break; sleep 2; done
curl -sf "http://$CFG_HOST:$CFG_PORT/api/scenarios" >/dev/null \
  || { echo "app did not answer; check: docker compose logs coach" >&2; exit 1; }

say "Daily backup (03:30, keeps 14 days)"
CRON="30 3 * * * cd $DIR && /usr/bin/python3 deploy/backup.py"
( crontab -u "$RUN_USER" -l 2>/dev/null | grep -v 'deploy/backup.py' || true; echo "$CRON" ) | crontab -u "$RUN_USER" -

say "Done: http://$CFG_HOST:$CFG_PORT"
echo "Check the models on your hardware: uv run bench/run.py $CHAT   (see AGENTS.md)"
