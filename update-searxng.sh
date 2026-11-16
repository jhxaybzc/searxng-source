#!/bin/sh
[ "$1" = force ] || docker pull searxng/searxng | grep -q "Downloaded newer image" || exit 0
P=/home/pi/searxng-patches; M=""
for f in "$P"/*.py; do [ -e "$f" ] && M="$M -v $f:/usr/local/searxng/searx/engines/$(basename "$f"):ro"; done
docker stop searxng && docker rm searxng
docker run -d --name searxng --restart unless-stopped -p 8888:8080 --network searx -e PYTHONPYCACHEPREFIX=/tmp/pycache -v /home/pi/searxng:/etc/searxng $M searxng/searxng
docker network connect proxy-net searxng
docker image prune -f
