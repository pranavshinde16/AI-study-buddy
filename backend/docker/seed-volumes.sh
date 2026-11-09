#!/bin/sh
# One-time copy of the dev storage folder (mounted read-only at /seed) into the Docker volumes:
#   /seed/chroma      -> /data/chroma   (vector store)
#   everything else   -> /data/storage  (uploads, audio, ...)
# Run with:  docker compose --profile seed run --rm seed
# Refuses to overwrite a volume that already has data unless SEED_FORCE=1.
set -e

if [ ! -d /seed ] || [ -z "$(ls -A /seed 2>/dev/null)" ]; then
    echo "Nothing to copy: ./storage is empty or missing."
    exit 0
fi

for dest in /data/storage /data/chroma; do
    if [ -n "$(ls -A "$dest" 2>/dev/null)" ] && [ "${SEED_FORCE:-0}" != "1" ]; then
        echo "$dest already has data. Not copying. Set SEED_FORCE=1 to copy over it."
        exit 1
    fi
done

for item in /seed/* /seed/.[!.]*; do
    [ -e "$item" ] || continue
    [ "$(basename "$item")" = "chroma" ] && continue
    cp -a "$item" /data/storage/
done
if [ -d /seed/chroma ]; then
    cp -a /seed/chroma/. /data/chroma/
fi

chown -R 1000:1000 /data/storage /data/chroma
echo "Copied. storage: $(du -sh /data/storage | cut -f1), chroma: $(du -sh /data/chroma | cut -f1)"
